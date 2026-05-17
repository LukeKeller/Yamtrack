"""Resolve scrobbles to MusicBrainz IDs via the ListenBrainz API.

We don't need the listen to match a record the user tracks — the point
is to give every scrobble a stable link out to MusicBrainz (and, by
extension, ListenBrainz) for "more details".

The ListenBrainz metadata lookup endpoint maps a free-text
(artist, recording) pair to canonical MBIDs:

    GET https://api.listenbrainz.org/1/metadata/lookup/
        ?artist_name=...&recording_name=...

No API key required. Responses are cached (including misses) so repeats
of the same track — very common in a scrobble history — cost one request.
Results are persisted as :class:`integrations.models.PlayMBID` rows; a
row with empty MBIDs records a definitive miss so backfill is idempotent.
"""

from __future__ import annotations

import hashlib
import logging
import time

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

LOOKUP_URL = "https://api.listenbrainz.org/1/metadata/lookup/"
USER_AGENT = "Yamtrack/1.0 (+https://github.com/LukeKeller/Yamtrack)"
CACHE_TTL = 60 * 60 * 24 * 30  # 30 days
REQUEST_TIMEOUT = 8
HTTP_TOO_MANY = 429
HTTP_OK = 200


def _cache_key(artist, recording):
    digest = hashlib.sha1(  # noqa: S324  non-crypto cache key
        f"{artist}\x1f{recording}".lower().encode("utf-8", "ignore"),
    ).hexdigest()
    return f"lb-mb:{digest}"


def lookup(artist, recording, release=""):  # noqa: ARG001  release kept for callers
    """Return the ListenBrainz mapping dict for (artist, recording).

    Returns ``{}`` for a definitive "no match" (cached), or ``None`` for a
    transient failure (rate limited / network / bad JSON) so the caller
    can leave the Play for a later retry instead of recording a miss.
    """
    artist = (artist or "").strip()
    recording = (recording or "").strip()
    if not artist or not recording:
        return {}

    key = _cache_key(artist, recording)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            LOOKUP_URL,
            params={"artist_name": artist, "recording_name": recording},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        logger.debug("ListenBrainz lookup failed for %s - %s", artist, recording)
        return None

    if resp.status_code == HTTP_TOO_MANY:
        return None
    if resp.status_code != HTTP_OK:
        # 4xx (other than rate limit) is a definitive miss; cache it.
        cache.set(key, {}, CACHE_TTL)
        return {}

    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        data = {}

    cache.set(key, data, CACHE_TTL)
    return data


def enrich_pending(limit=500, sleep=0.1):
    """Resolve MBIDs for ListenBrainz Plays that have no PlayMBID yet.

    Returns a counts dict. ``sleep`` throttles requests to be polite to
    the ListenBrainz API (cache hits don't sleep).
    """
    from app.models import Play, PlaySource  # noqa: PLC0415
    from integrations.models import PlayMBID  # noqa: PLC0415

    rows = list(
        Play.objects.filter(
            source=PlaySource.LISTENBRAINZ.value,
            mbid__isnull=True,
        )
        .only("id", "artist", "title", "album")
        .order_by("id")[:limit],
    )

    created = matched = 0
    for play in rows:
        key = _cache_key((play.artist or "").strip(), (play.title or "").strip())
        was_cached = cache.get(key) is not None

        data = lookup(play.artist, play.title, play.album)
        if data is None:
            continue  # transient: leave for a later run

        artist_mbids = data.get("artist_mbids") or []
        PlayMBID.objects.create(
            play=play,
            recording_mbid=data.get("recording_mbid") or "",
            release_mbid=data.get("release_mbid") or "",
            artist_mbid=artist_mbids[0] if artist_mbids else "",
        )
        created += 1
        if data.get("recording_mbid"):
            matched += 1

        if sleep and not was_cached:
            time.sleep(sleep)

    logger.info(
        "MBID enrichment: scanned=%s created=%s matched=%s",
        len(rows),
        created,
        matched,
    )
    return {"scanned": len(rows), "created": created, "matched": matched}
