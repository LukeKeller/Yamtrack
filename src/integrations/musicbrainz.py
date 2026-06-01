"""Resolve scrobbles to MusicBrainz IDs via the MusicBrainz web service.

We don't need the listen to match a record the user tracks - the point
is to give every scrobble a stable link out to MusicBrainz for "more
details".

We query the public MusicBrainz search API (no auth, unlike the
ListenBrainz metadata lookup which requires a user token):

    GET https://musicbrainz.org/ws/2/recording/
        ?query=recording:"..." AND artist:"..."&fmt=json

MusicBrainz asks for <= 1 request/second and a descriptive User-Agent;
``enrich_pending`` throttles accordingly. Responses are cached
(including genuine "no match") so repeats of the same track - very
common in a scrobble history - cost one request. Transient failures
(timeouts, 5xx, 503 rate-limit) return ``None`` and are NOT cached or
recorded, so they're retried on the next run instead of poisoning the
history with permanent misses.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
# MusicBrainz requires a meaningful UA identifying the app + contact/URL.
USER_AGENT = "Yamtrack/1.0 ( https://github.com/LukeKeller/Yamtrack )"
CACHE_TTL = 60 * 60 * 24 * 30  # 30 days
REQUEST_TIMEOUT = 12
HTTP_OK = 200
# Minimum MusicBrainz search score (0-100) to accept the top hit. High
# enough to avoid wrong links, low enough to catch punctuation/case drift.
MIN_SCORE = 85


def _cache_key(artist, recording):
    digest = hashlib.sha1(  # noqa: S324  non-crypto cache key
        f"{artist}\x1f{recording}".lower().encode("utf-8", "ignore"),
    ).hexdigest()
    return f"mb-rec:{digest}"


def _lucene_escape(text):
    """Escape characters significant to the MusicBrainz/Lucene query parser."""
    return re.sub(r'(["\\])', r"\\\1", text)


def _select_release(recording, album):
    """Pick the release MBID, preferring one whose title matches the album."""
    releases = recording.get("releases") or []
    if not releases:
        return ""
    if album:
        target = album.strip().lower()
        for rel in releases:
            if (rel.get("title") or "").strip().lower() == target:
                return rel.get("id") or ""
    return releases[0].get("id") or ""


def lookup(artist, recording, release=""):  # noqa: PLR0911
    """Return ``{recording_mbid, release_mbid, artist_mbids}`` for a listen.

    ``{}`` means a definitive no-match (cached). ``None`` means a
    transient failure (network / 5xx / rate-limit / bad JSON) - the
    caller should skip it and retry later, NOT record a miss.
    """
    artist = (artist or "").strip()
    recording_name = (recording or "").strip()
    if not artist or not recording_name:
        return {}

    key = _cache_key(artist, recording_name)
    cached = cache.get(key)
    if cached is not None:
        return cached

    query = (
        f'recording:"{_lucene_escape(recording_name)}" '
        f'AND artist:"{_lucene_escape(artist)}"'
    )
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"query": query, "fmt": "json", "limit": 3},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        logger.debug("MusicBrainz lookup failed for %s - %s", artist, recording)
        return None

    if resp.status_code != HTTP_OK:
        # 503 = rate limited, 5xx = server. Transient: don't cache/record.
        logger.debug("MusicBrainz HTTP %s for %s", resp.status_code, query)
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    recordings = data.get("recordings") or []
    if not recordings:
        cache.set(key, {}, CACHE_TTL)  # genuine no-match
        return {}

    best = recordings[0]
    try:
        score = int(best.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    if score < MIN_SCORE:
        cache.set(key, {}, CACHE_TTL)
        return {}

    credit = best.get("artist-credit") or []
    artist_mbid = ""
    if credit:
        artist_mbid = (credit[0].get("artist") or {}).get("id") or ""

    result = {
        "recording_mbid": best.get("id") or "",
        "release_mbid": _select_release(best, release),
        "artist_mbids": [artist_mbid] if artist_mbid else [],
    }
    cache.set(key, result, CACHE_TTL)
    return result


def enrich_pending(limit=500, sleep=1.1):
    """Resolve MBIDs for ListenBrainz Plays that have no PlayMBID yet.

    Returns a counts dict. ``sleep`` throttles live MusicBrainz requests
    (default ~1/s per MB policy); cache hits don't sleep.
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
