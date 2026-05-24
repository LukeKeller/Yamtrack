"""Yamtrack <-> Hardcover field & identity mapping.

Two concerns live together because future-you needs them in the same
place when reading "what does sync do":

1. **Book identity** -- map a Yamtrack ``Item`` to a Hardcover
   ``book_id``. ``Item.source == 'hardcover'`` is the fast path
   (``Item.media_id`` IS the book id). For ``openlibrary`` (the default
   book provider) we resolve via ISBN-13 lookup, falling back to a
   title+author search. Winners are cached in ``HardcoverBookMapping``.

2. **Field mapping** -- paired ``*_to_yamtrack`` / ``*_to_hardcover``
   helpers for status, score/rating, dates, and progress. Both
   directions live next to each other so the round-trip
   (``yamtrack -> hardcover -> yamtrack``) is by-construction stable
   (see ``score_to_hardcover`` / ``score_to_yamtrack``). The inbound
   importer and the outbound push task both go through here; nothing
   else should hard-code a Hardcover ``status_id`` or rating scale.
"""

import logging
from datetime import UTC, datetime

from django.utils.dateparse import parse_datetime

from app.models import Sources, Status
from app.providers import openlibrary
from app.providers.services import ProviderAPIError
from integrations import hardcover_client
from integrations.models import HardcoverBookMapping

logger = logging.getLogger(__name__)


class HardcoverResolveError(Exception):
    """Could not resolve a Yamtrack Item to any Hardcover book."""


# ---------------------------------------------------------------------------
# Field mappings
# ---------------------------------------------------------------------------

# Hardcover ``status_id`` -> Yamtrack ``Status`` value.
_HC_TO_YAMTRACK_STATUS = {
    1: Status.PLANNING.value,  # Want to Read
    2: Status.IN_PROGRESS.value,  # Currently Reading
    3: Status.COMPLETED.value,  # Read
    4: Status.PAUSED.value,  # Paused
    5: Status.DROPPED.value,  # Did Not Finish
}

# Inverse of the above. Built once so both directions can never drift.
_YAMTRACK_TO_HC_STATUS = {v: k for k, v in _HC_TO_YAMTRACK_STATUS.items()}

# When Hardcover hands us a status we don't recognise (new statuses,
# bugs), the inbound importer skips the row -- silent default would be
# worse. The outbound side falls back to "Currently Reading" because a
# missing Yamtrack status is rarer and the user can correct it from
# Hardcover's UI; see ``status_to_hardcover``.
_HC_FALLBACK_STATUS_ID = 2


def status_to_yamtrack(hc_status_id):
    """Hardcover ``status_id`` -> Yamtrack ``Status.value``, or None if unknown."""
    return _HC_TO_YAMTRACK_STATUS.get(hc_status_id)


def status_to_hardcover(yamtrack_status):
    """Yamtrack ``Status.value`` -> Hardcover ``status_id``.

    Falls back to "Currently Reading" if the status is unfamiliar -- better
    than crashing the push job, and the user can correct from Hardcover's UI.
    """
    return _YAMTRACK_TO_HC_STATUS.get(yamtrack_status, _HC_FALLBACK_STATUS_ID)


def score_to_yamtrack(hc_rating):
    """Hardcover rating (0..5, half-step) -> Yamtrack score (0..10, one decimal).

    Returns ``None`` for a missing/None rating. ``0`` means "no rating" in
    Yamtrack, so we keep ``0.0`` on the Hardcover side mapped to ``0`` here
    deliberately -- the importer is free to skip writing it.
    """
    if hc_rating is None:
        return None
    return round(float(hc_rating) * 2, 1)


def score_to_hardcover(yamtrack_score):
    """Yamtrack score (0..10, one decimal) -> Hardcover rating (0..5, half-step).

    Returns ``None`` when there's no rating (Yamtrack stores ``None``, not 0,
    for "unrated"). Rounded to the nearest 0.5 so the round-trip
    ``9.0 -> 4.5 -> 9.0`` is stable.
    """
    if yamtrack_score is None:
        return None
    # Half-step rounding on 0..5 scale.
    return round(float(yamtrack_score) / 2 * 2) / 2


def parse_hc_date(raw):
    """Parse a Hardcover ``YYYY-MM-DD`` or ISO datetime string -> aware datetime."""
    if not raw:
        return None
    dt = parse_datetime(raw)
    if dt:
        return dt
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def dates_read_input(book, edition_id):
    """Build the ``DatesReadInput`` GraphQL payload from a ``Book`` row.

    Only emits fields that are actually set; Hardcover treats absent
    fields as "no change", which is what we want.
    """
    payload = {}
    if book.progress:
        payload["progress_pages"] = int(book.progress)
    if book.start_date:
        payload["started_at"] = book.start_date.date().isoformat()
    if book.end_date:
        payload["finished_at"] = book.end_date.date().isoformat()
    if edition_id:
        payload["edition_id"] = int(edition_id)
    return payload


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
