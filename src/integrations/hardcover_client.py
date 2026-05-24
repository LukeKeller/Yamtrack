"""Shared GraphQL client for Hardcover (read + write).

Both the existing inbound importer (``integrations.imports.hardcover``)
and the outbound push pipeline (``integrations.tasks.push_book_to_hardcover``)
talk to the same endpoint with the same auth header shape, so the
HTTP/auth/error layer lives here once.

The Hardcover API is beta: tokens reset annually, the schema can shift,
and the rate cap is 60 req/min (we lean on the shared
``app.providers.services`` ``LimiterSession`` for that). Mutations are
small — a single ``insert_user_book_read`` per Yamtrack progress save —
so a per-call HTTP round trip is fine; no batching needed.
"""

import logging

import requests

from app.models import Sources
from app.providers import services

logger = logging.getLogger(__name__)

HARDCOVER_API_URL = "https://api.hardcover.app/v1/graphql"


class HardcoverAPIError(Exception):
    """Generic Hardcover GraphQL error (returned via the `errors` field)."""


class HardcoverAuthError(HardcoverAPIError):
    """401/403 from Hardcover — token invalid or expired (annual reset)."""


def normalize_token(token):
    """Return the token with a Bearer prefix if missing.

    Hardcover's docs are inconsistent about whether to include "Bearer ";
    in practice they require it. Accept both shapes from the user.
    """
    token = (token or "").strip()
    if not token:
        return token
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def execute(query, variables, token):
    """Run a GraphQL query and return the data dict.

    Raises ``HardcoverAuthError`` on 401/403 and ``HardcoverAPIError`` for
    any GraphQL ``errors`` payload. Other HTTP errors propagate so the
    shared ``services.api_request`` retry/back-off path can run.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": normalize_token(token),
    }
    try:
        response = services.api_request(
            Sources.HARDCOVER.value,
            "POST",
            HARDCOVER_API_URL,
            params={"query": query, "variables": variables},
            headers=headers,
        )
    except requests.exceptions.HTTPError as error:
        status = error.response.status_code
        if status in (requests.codes.unauthorized, requests.codes.forbidden):
            msg = "Invalid or expired Hardcover API token."
            raise HardcoverAuthError(msg) from error
        raise

    if response.get("errors"):
        first = response["errors"][0].get("message", "Unknown Hardcover API error.")
        msg = f"Hardcover API error: {first}"
        raise HardcoverAPIError(msg)

    return response.get("data") or {}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


ME_QUERY = "query { me { id username } }"


def get_me(token):
    """Validate the token; return (hardcover_user_id, username)."""
    data = execute(ME_QUERY, {}, token)
    me_list = data.get("me") or []
    if not me_list:
        msg = "Could not look up Hardcover account for this token."
        raise HardcoverAPIError(msg)
    return me_list[0]["id"], me_list[0]["username"]


USER_BOOK_FOR_BOOK_QUERY = """
query ($book_id: Int!) {
  me {
    user_books(where: {book_id: {_eq: $book_id}}, limit: 1) {
      id
      status_id
      rating
      user_book_reads(
        order_by: {finished_at: desc_nulls_last, started_at: desc_nulls_last}
      ) {
        id
        progress_pages
        started_at
        finished_at
        edition_id
      }
    }
  }
}
"""


def get_user_book_for_book(book_id, token):
    """Return the user's existing ``user_book`` for a given Hardcover book.

    Returns ``None`` if the user doesn't have the book; otherwise a dict
    with ``id``, ``status_id``, ``rating``, and ``user_book_reads`` (newest
    first — element 0 is the latest read).
    """
    data = execute(USER_BOOK_FOR_BOOK_QUERY, {"book_id": int(book_id)}, token)
    me_list = data.get("me") or []
    if not me_list:
        return None
    user_books = me_list[0].get("user_books") or []
    return user_books[0] if user_books else None


EDITION_BY_ISBN13_QUERY = """
query ($isbn: String!) {
  editions(where: {isbn_13: {_eq: $isbn}}, limit: 1) {
    id
    book { id }
  }
}
"""


def find_edition_by_isbn13(isbn, token):
    """Return (book_id, edition_id) for an ISBN-13, or (None, None)."""
    data = execute(EDITION_BY_ISBN13_QUERY, {"isbn": str(isbn)}, token)
    editions = data.get("editions") or []
    if not editions:
        return None, None
    edition = editions[0]
    book = edition.get("book") or {}
    return book.get("id"), edition.get("id")


SEARCH_BOOK_QUERY = """
query ($q: String!) {
  search(query: $q, query_type: "Book", per_page: 5, page: 1) {
    results
  }
}
"""


def search_book(query, token):
    """Return the raw Typesense hits for a Hardcover book search.

    Caller is responsible for picking the best match from the list — the
    shape is ``{results: {hits: [{document: {id, title, author_names, ...}}]}}``.
    """
    data = execute(SEARCH_BOOK_QUERY, {"q": query}, token)
    results = data.get("search") or {}
    return ((results.get("results") or {}).get("hits")) or []


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


INSERT_USER_BOOK_MUTATION = """
mutation ($book_id: Int!, $status_id: Int!) {
  insert_user_book(object: {book_id: $book_id, status_id: $status_id}) {
    id
    error
  }
}
"""


def insert_user_book(book_id, status_id, token):
    """Add a book to the user's Hardcover library; return the user_book id."""
    data = execute(
        INSERT_USER_BOOK_MUTATION,
        {"book_id": int(book_id), "status_id": int(status_id)},
        token,
    )
    payload = data.get("insert_user_book") or {}
    if payload.get("error"):
        raise HardcoverAPIError(payload["error"])
    return payload.get("id")


UPDATE_USER_BOOK_MUTATION = """
mutation ($id: Int!, $object: UserBookUpdateInput!) {
  update_user_book(id: $id, object: $object) {
    id
    error
  }
}
"""


def update_user_book(user_book_id, fields, token):
    """Update an existing user_book (status, rating, etc.)."""
    data = execute(
        UPDATE_USER_BOOK_MUTATION,
        {"id": int(user_book_id), "object": fields},
        token,
    )
    payload = data.get("update_user_book") or {}
    if payload.get("error"):
        raise HardcoverAPIError(payload["error"])
    return payload.get("id")


INSERT_USER_BOOK_READ_MUTATION = """
mutation ($user_book_id: Int!, $user_book_read: DatesReadInput!) {
  insert_user_book_read(
    user_book_id: $user_book_id,
    user_book_read: $user_book_read,
  ) {
    id
    error
  }
}
"""


def insert_user_book_read(user_book_id, dates_read_input, token):
    """Start a new reading session (or back-fill one); return its id."""
    data = execute(
        INSERT_USER_BOOK_READ_MUTATION,
        {
            "user_book_id": int(user_book_id),
            "user_book_read": dates_read_input,
        },
        token,
    )
    payload = data.get("insert_user_book_read") or {}
    if payload.get("error"):
        raise HardcoverAPIError(payload["error"])
    return payload.get("id")


UPDATE_USER_BOOK_READ_MUTATION = """
mutation ($id: Int!, $object: DatesReadInput!) {
  update_user_book_read(id: $id, object: $object) {
    id
    error
  }
}
"""


def update_user_book_read(read_id, dates_read_input, token):
    """Update an existing reading session (e.g. bump progress_pages)."""
    data = execute(
        UPDATE_USER_BOOK_READ_MUTATION,
        {"id": int(read_id), "object": dates_read_input},
        token,
    )
    payload = data.get("update_user_book_read") or {}
    if payload.get("error"):
        raise HardcoverAPIError(payload["error"])
    return payload.get("id")
