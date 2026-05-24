"""Resolve a Yamtrack ``Item`` to a Hardcover ``book_id``.

``Item.source == 'hardcover'`` is the fast path — ``Item.media_id`` IS
the Hardcover book id, so no API call. For ``openlibrary`` (the default
book provider), we resolve via ISBN-13 lookup, falling back to a
title+author search if no ISBN is present. The winner is cached in
``HardcoverBookMapping`` so the next push for the same book skips the
round trip.

We don't currently support reverse direction (mapping a Yamtrack book to
Hardcover when the user changes books between sources mid-tracking) —
the cache row is keyed on ``item.pk``, which is stable.
"""

import logging

from app.models import Sources
from app.providers import openlibrary
from app.providers.services import ProviderAPIError
from integrations import hardcover_client
from integrations.models import HardcoverBookMapping

logger = logging.getLogger(__name__)


class HardcoverResolveError(Exception):
    """Could not resolve a Yamtrack Item to any Hardcover book."""


def resolve_book_id(item, token):
    """Return ``(hardcover_book_id, hardcover_edition_id, match_method)``.

    Caches the result in ``HardcoverBookMapping`` on success. Re-raises
    auth errors verbatim so the caller can disable the integration; wraps
    "no match found" as ``HardcoverResolveError`` so signal/task code can
    distinguish "permanent miss" from "transient API failure".
    """
    if item.source == Sources.HARDCOVER.value:
        # Hardcover-sourced items already carry the book id.
        return int(item.media_id), None, HardcoverBookMapping.MatchMethod.DIRECT_ID

    cached = HardcoverBookMapping.objects.filter(item=item).first()
    if cached:
        return (
            cached.hardcover_book_id,
            cached.hardcover_edition_id,
            cached.match_method,
        )

    book_id, edition_id, method = _resolve_uncached(item, token)
    HardcoverBookMapping.objects.update_or_create(
        item=item,
        defaults={
            "hardcover_book_id": book_id,
            "hardcover_edition_id": edition_id,
            "match_method": method,
        },
    )
    return book_id, edition_id, method


def _resolve_uncached(item, token):
    """Resolve without consulting the cache. Used by ``resolve_book_id``."""
    isbns = _gather_isbns(item)
    for isbn in isbns:
        if len(str(isbn)) != 13:  # noqa: PLR2004
            continue
        book_id, edition_id = hardcover_client.find_edition_by_isbn13(isbn, token)
        if book_id:
            logger.info("Resolved %s via ISBN-13 %s → HC book %s", item, isbn, book_id)
            return book_id, edition_id, HardcoverBookMapping.MatchMethod.ISBN

    # Fallback: full-text search by title (and disambiguate by author).
    title = item.title or ""
    if not title:
        msg = f"Item {item.pk} has no title; cannot search Hardcover."
        raise HardcoverResolveError(msg)

    hits = hardcover_client.search_book(title, token)
    matched = _pick_best_hit(hits, item)
    if matched:
        logger.info("Resolved %s via title+author search → HC book %s", item, matched)
        return matched, None, HardcoverBookMapping.MatchMethod.TITLE_AUTHOR

    msg = f"No Hardcover match for {item} (title='{title}', ISBNs={isbns or 'none'})."
    raise HardcoverResolveError(msg)


def _gather_isbns(item):
    """Pull ISBN-13s (and ISBN-10s as fallback) from the OpenLibrary metadata.

    We don't store ISBN on ``Item`` — but ``openlibrary.book()`` returns
    them, and the response is Redis-cached for 24h, so this is cheap.
    Returns a list (preserves insertion order so 13s are tried first).
    """
    try:
        metadata = openlibrary.book(item.media_id)
    except ProviderAPIError:
        logger.warning("Could not fetch OL metadata for %s; ISBN lookup skipped.", item)
        return []
    details = metadata.get("details") or {}
    raw = details.get("isbn") or []
    # ``get_isbns`` returns ISBN-13s first, then 10s; preserve that ordering.
    return [str(i) for i in raw if i]


def _pick_best_hit(hits, item):
    """Pick the best Hardcover search hit for an Item, or return None.

    We require a title prefix match plus, when ``item.publisher`` or any
    author signal is available, at least a weak author overlap. The bar
    is intentionally conservative because a wrong match is worse than
    no match (silent data drift to a stranger's book).
    """
    if not hits:
        return None
    target_title = (item.title or "").lower().strip()
    target_author = (item.artist or "").lower().strip()
    for hit in hits:
        doc = (hit.get("document") or {}) if isinstance(hit, dict) else {}
        candidate_title = (doc.get("title") or "").lower().strip()
        candidate_authors = " ".join(doc.get("author_names") or []).lower()
        if not candidate_title or not candidate_title.startswith(target_title[:24]):
            continue
        if target_author and target_author.split()[0] not in candidate_authors:
            continue
        book_id = doc.get("id")
        if book_id:
            return int(book_id)
    return None
