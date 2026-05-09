"""ListenBrainz-compatible scrobble receiver.

Multi-scrobbler (and similar tools) send listens via the ListenBrainz API
v1 protocol. Yamtrack accepts those listens here, maps them to ``Item``
rows by case-insensitive (artist, title) match, and writes ``Play`` rows.

Unmatched scrobbles are still persisted as text-only — they show up in
listening activity but don't link to a tracked record. Listens of type
``playing_now`` are intentionally not persisted (they're transient
"currently playing" pings, not completed plays).

Protocol reference:
https://listenbrainz.readthedocs.io/en/latest/users/api/core.html#post--1-submit-listens
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.utils import timezone

from app.models import Item, MediaTypes, Play, PlaySource, Sources

logger = logging.getLogger(__name__)

LISTEN_TYPES_PERSIST = {"single", "import"}
LISTEN_TYPES_IGNORE = {"playing_now"}


def extract_bearer_token(request):
    """Pull the bearer/token from a ListenBrainz Authorization header.

    ListenBrainz uses ``Authorization: Token XXX``; some clients still
    send ``Authorization: Bearer XXX``. Accept both.
    """
    raw = request.headers.get("Authorization", "")
    if not raw:
        return ""
    parts = raw.strip().split(None, 1)
    expected_parts = 2
    if len(parts) != expected_parts:
        return ""
    scheme, value = parts[0].lower(), parts[1].strip()
    if scheme not in ("token", "bearer"):
        return ""
    return value


def submit_listens(user, body):
    """Persist a ListenBrainz payload as Play rows for the given user.

    Returns the count of persisted Plays. Raises ``ValueError`` for malformed
    payloads so the view can return a structured 400.
    """
    if not isinstance(body, dict):
        msg = "Body must be a JSON object."
        raise ValueError(msg)  # noqa: TRY004

    listen_type = body.get("listen_type", "single")
    if listen_type in LISTEN_TYPES_IGNORE:
        return 0
    if listen_type not in LISTEN_TYPES_PERSIST:
        msg = f"Unsupported listen_type: {listen_type!r}"
        raise ValueError(msg)

    payload = body.get("payload")
    if not isinstance(payload, list):
        msg = "payload must be a list."
        raise ValueError(msg)  # noqa: TRY004

    plays = []
    for entry in payload:
        play = _build_play(user, entry)
        if play:
            plays.append(play)

    if plays:
        Play.objects.bulk_create(plays, batch_size=200)

    logger.info(
        "Persisted %s ListenBrainz listens (out of %s) for user %s",
        len(plays),
        len(payload),
        user.username,
    )
    return len(plays)


def _build_play(user, entry):
    """Convert one ListenBrainz listen entry into an unsaved Play."""
    if not isinstance(entry, dict):
        return None

    metadata = entry.get("track_metadata") or {}
    artist = (metadata.get("artist_name") or "").strip()
    title = (metadata.get("track_name") or "").strip()
    album = (metadata.get("release_name") or "").strip()
    if not (artist or title):
        return None

    listened_at = _parse_listened_at(entry.get("listened_at"))
    additional = metadata.get("additional_info") or {}
    duration_ms = additional.get("duration_ms")
    duration_seconds = None
    if isinstance(duration_ms, int) and duration_ms > 0:
        duration_seconds = duration_ms // 1000
    elif isinstance(additional.get("duration"), int):
        duration_seconds = additional["duration"]

    return Play(
        user=user,
        item=match_item(artist, title, album),
        artist=artist,
        title=title,
        album=album,
        played_at=listened_at,
        duration_seconds=duration_seconds,
        source=PlaySource.LISTENBRAINZ.value,
        side="",
    )


def _parse_listened_at(value):
    """Parse a ListenBrainz ``listened_at`` (Unix seconds) into a datetime."""
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    return timezone.now()


def match_item(artist, title, album=""):
    """Case-insensitive (artist, title) match against existing Items.

    Falls back to (artist, album) so "playing this album" scrobbles still
    bind to the right record. Returns the first match, or None.
    """
    if not artist:
        return None

    # Match against the Item.title exactly first (Discogs records are stored
    # as "Artist - Title" today, so the track scrobble's ``release_name``
    # often matches the record's ``title`` via the (artist,) prefix).
    if title:
        track = Item.objects.filter(
            media_type=MediaTypes.RECORD.value,
            artist__iexact=artist,
            title__iexact=title,
        ).first()
        if track:
            return track

    if album:
        record = Item.objects.filter(
            media_type=MediaTypes.RECORD.value,
            source=Sources.DISCOGS.value,
            artist__iexact=artist,
            title__icontains=album,
        ).first()
        if record:
            return record

    # Last-resort: any item by this artist where the title contains the track.
    if title:
        return Item.objects.filter(
            media_type=MediaTypes.RECORD.value,
            artist__iexact=artist,
            title__icontains=title,
        ).first()

    return None
