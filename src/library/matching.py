"""Resolve an uploaded LibraryFile to a metadata provider work.

"Matched" now means "resolved to a provider work" (Hardcover or
OpenLibrary), independent of whether the user tracks the Book. This
module owns that one concern: take a ``LibraryFile`` and bind its
``item`` FK to the right provider ``Item``, recording how.

Provider strategy (per the agreed design):

* Try **Hardcover first** only if the file's user has a usable
  ``HardcoverIntegration`` token. Resolve by ISBN-13, then a
  conservative title+author search.
* Fall back to **OpenLibrary** (keyless) when there's no Hardcover
  token or Hardcover misses. Resolve ISBN via the ``/isbn/<isbn>.json``
  redirect to an edition key, then a conservative title+author search.

ISBN is normalised first: ``isbn_13`` wins; an ``isbn_10`` is converted
to ISBN-13 (978 prefix + recomputed check digit). At most one ISBN
lookup plus one search per provider, so a bulk upload can't blow the
rate budget.

A clean "no hit" leaves the row ``NO_MATCH``; a provider/API *error*
(timeout, 5xx, GraphQL error) leaves it ``UNRESOLVED`` so a later retry
can run. ``resolve_library_file_to_provider`` catches everything and
never raises out to the task.
"""

from __future__ import annotations

import logging

import requests
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.providers import hardcover, openlibrary, services
from library.models import LibraryFile

logger = logging.getLogger(__name__)

ISBN_13_LEN = 13
ISBN_10_LEN = 10

# Conservative title-prefix window for search disambiguation -- mirrors
# ``integrations.hardcover_mapping._pick_best_hit``.
_TITLE_PREFIX_LEN = 24


def isbn10_to_isbn13(isbn_10):
    """Convert a 10-char ISBN-10 to ISBN-13 (978 prefix + new check digit).

    Returns "" if the input isn't a well-formed ISBN-10 (the trailing
    check char may be ``X`` but the first 9 must be digits).
    """
    raw = (isbn_10 or "").strip().upper().replace("-", "").replace(" ", "")
    if len(raw) != ISBN_10_LEN or not raw[:9].isdigit():
        return ""
    core = "978" + raw[:9]
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(core))
    check = (10 - (total % 10)) % 10
    return f"{core}{check}"


def _normalised_isbn13(library_file):
    """Return a usable ISBN-13 for the file, or "" if none."""
    raw13 = (library_file.isbn_13 or "").strip().replace("-", "").replace(" ", "")
    if len(raw13) == ISBN_13_LEN and raw13.isdigit():
        return raw13
    return isbn10_to_isbn13(library_file.isbn_10)


def _hardcover_token(library_file):
    """Return a decrypted, usable Hardcover token for the user, or None."""
    from integrations.imports import helpers as import_helpers  # noqa: PLC0415
    from integrations.models import HardcoverIntegration  # noqa: PLC0415

    integration = HardcoverIntegration.objects.filter(
        user=library_file.user,
        enabled=True,
    ).first()
    if not integration or not integration.api_token:
        return None
    try:
        token = import_helpers.decrypt(integration.api_token)
    except Exception:
        # A bad/garbled token must not raise; treat it as "no token".
        logger.exception(
            "Could not decrypt Hardcover token for user %s",
            library_file.user_id,
        )
        return None
    return token or None


def _author_overlaps(target_author, candidate_authors):
    """Weak author-overlap test (first token of the upload author present)."""
    target = (target_author or "").lower().strip()
    if not target:
        # No author signal to disambiguate on -- accept on title alone.
        return True
    return target.split()[0] in (candidate_authors or "").lower()


def _title_prefix_matches(target_title, candidate_title):
    """Conservative title-prefix match (mirrors hardcover_mapping)."""
    target = (target_title or "").lower().strip()
    candidate = (candidate_title or "").lower().strip()
    return bool(candidate) and candidate.startswith(target[:_TITLE_PREFIX_LEN])


def _resolve_hardcover(library_file, isbn13, token):
    """Return (media_id, title, image, method) for a Hardcover hit, or None.

    ``method`` is the ``LibraryFile.MatchMethod`` value (ISBN or
    TITLE_AUTHOR). One ISBN lookup plus at most one search. Returns
    ``None`` only on a genuine "no hit"; provider/API errors propagate so
    the caller can leave the row UNRESOLVED rather than NO_MATCH.
    """
    from integrations import hardcover_client  # noqa: PLC0415

    book_id = None
    method = None

    if isbn13:
        book_id, _edition_id = hardcover_client.find_edition_by_isbn13(isbn13, token)
        if book_id:
            method = LibraryFile.MatchMethod.ISBN

    if not book_id and library_file.title:
        hits = hardcover_client.search_book(library_file.title, token)
        book_id = _pick_hardcover_hit(hits, library_file)
        if book_id:
            method = LibraryFile.MatchMethod.TITLE_AUTHOR

    if not book_id:
        return None

    metadata = hardcover.book(book_id)
    return str(book_id), metadata.get("title", ""), metadata.get("image", ""), method


def _pick_hardcover_hit(hits, library_file):
    """Pick a conservative Hardcover search hit, or None."""
    for hit in hits or []:
        doc = (hit.get("document") or {}) if isinstance(hit, dict) else {}
        candidate_title = doc.get("title") or ""
        candidate_authors = " ".join(doc.get("author_names") or [])
        if not _title_prefix_matches(library_file.title, candidate_title):
            continue
        if not _author_overlaps(library_file.author, candidate_authors):
            continue
        book_id = doc.get("id")
        if book_id:
            return book_id
    return None


def _openlibrary_edition_for_isbn(isbn13):
    """Resolve an ISBN-13 to an OpenLibrary edition key (``OL...M``), or None.

    A 404 ("no such ISBN") is a clean miss and returns ``None``; other
    transport errors propagate so the caller leaves the row UNRESOLVED.
    """
    url = f"https://openlibrary.org/isbn/{isbn13}.json"
    try:
        data = services.api_request(Sources.OPENLIBRARY.value, "GET", url)
    except requests.HTTPError as error:
        response = error.response
        if response is not None and response.status_code == requests.codes.not_found:
            logger.info("OpenLibrary ISBN %s not found", isbn13)
            return None
        raise
    return openlibrary.extract_openlibrary_id(data.get("key", ""))


def _resolve_openlibrary(library_file, isbn13):
    """Return (media_id, title, image, method) for an OpenLibrary hit, or None.

    Returns ``None`` only on a genuine "no hit"; provider/API errors
    propagate so the caller can leave the row UNRESOLVED rather than
    NO_MATCH.
    """
    media_id = None
    method = None

    if isbn13:
        media_id = _openlibrary_edition_for_isbn(isbn13)
        if media_id:
            method = LibraryFile.MatchMethod.ISBN

    if not media_id and library_file.title:
        query = library_file.title
        if library_file.author:
            query = f"{library_file.title} {library_file.author}"
        results = openlibrary.search(query, 1)
        media_id = _pick_openlibrary_hit(results, library_file)
        if media_id:
            method = LibraryFile.MatchMethod.TITLE_AUTHOR

    if not media_id:
        return None

    metadata = openlibrary.book(media_id)
    return media_id, metadata.get("title", ""), metadata.get("image", ""), method


def _pick_openlibrary_hit(results, library_file):
    """Pick a conservative OpenLibrary search hit, or None.

    The search response carries no author per result, so we can only gate
    on a title-prefix match -- and we require a single unambiguous title to
    avoid binding to the wrong edition.
    """
    candidates = [
        result
        for result in (results or {}).get("results", [])
        if _title_prefix_matches(library_file.title, result.get("title", ""))
    ]
    if len(candidates) == 1:
        return candidates[0].get("media_id")
    return None


def _bind(library_file, source, media_id, title, image, method):
    """Get-or-create the provider Item and stamp the file as MATCHED."""
    item, _created = Item.objects.get_or_create(
        media_id=str(media_id),
        source=source,
        media_type=MediaTypes.BOOK.value,
        defaults={
            "title": title or library_file.title,
            "image": image or "",
        },
    )
    library_file.item = item
    library_file.match_status = LibraryFile.MatchStatus.MATCHED
    library_file.match_method = method
    library_file.matched_at = timezone.now()
    library_file.save(
        update_fields=[
            "item",
            "match_status",
            "match_method",
            "matched_at",
            "updated_at",
        ],
    )


def resolve_library_file_to_provider(library_file):
    """Resolve ``library_file`` to a provider work; return True on a match.

    Hardcover is tried first when the user has a usable token, then
    OpenLibrary. On a match the file's ``item`` is set and it's stamped
    MATCHED. On a clean miss it's stamped NO_MATCH. Provider/API errors
    are caught and the row is left UNRESOLVED for a later retry -- this
    function never raises.
    """
    isbn13 = _normalised_isbn13(library_file)

    token = _hardcover_token(library_file)
    if token:
        try:
            hit = _resolve_hardcover(library_file, isbn13, token)
        except Exception:
            # The resolver must never raise out of the task; log and fall through.
            logger.exception(
                "Unexpected Hardcover resolve error for %s",
                library_file,
            )
            hit = None
        if hit:
            media_id, title, image, method = hit
            _bind(library_file, Sources.HARDCOVER.value, media_id, title, image, method)
            return True

    try:
        hit = _resolve_openlibrary(library_file, isbn13)
    except Exception:
        # The resolver must never raise out of the task; leave the row
        # UNRESOLVED so a retry can run.
        logger.exception(
            "Unexpected OpenLibrary resolve error for %s",
            library_file,
        )
        return False

    if hit:
        media_id, title, image, method = hit
        _bind(library_file, Sources.OPENLIBRARY.value, media_id, title, image, method)
        return True

    library_file.match_status = LibraryFile.MatchStatus.NO_MATCH
    library_file.save(update_fields=["match_status", "updated_at"])
    return False
