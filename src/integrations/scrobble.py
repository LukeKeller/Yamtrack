"""ListenBrainz-compatible scrobble receiver.

Multi-scrobbler (and similar tools) send listens via the ListenBrainz API
v1 protocol. Yamtrack accepts those listens here, maps them to ``Item``
rows by case-insensitive (artist, title) match, and writes ``Play`` rows.

Unmatched scrobbles are still persisted as text-only — they show up in
listening activity but don't link to a tracked record. Listens of type
``playing_now`` are intentionally not persisted (they're transient
"currently playing" pings, not completed plays).

Multi-scrobbler also calls ``GET /1/user/<name>/listens`` before
submitting, to deduplicate against what the server already has. We
implement that here too (``get_user_listens``); without it multi-scrobbler
treats every scrobble cycle as failed and never submits anything.

Protocol reference:
https://listenbrainz.readthedocs.io/en/latest/users/api/core.html#post--1-submit-listens
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from django.utils import timezone

from app.models import Item, MediaTypes, Play, PlaySource, Sources

logger = logging.getLogger(__name__)

LISTEN_TYPES_PERSIST = {"single", "import"}
LISTEN_TYPES_IGNORE = {"playing_now"}

LISTENS_DEFAULT_COUNT = 25
LISTENS_MAX_COUNT = 1000

# Fixed namespace so a given Play always yields the same recording_msid.
_LISTEN_MSID_NS = uuid.UUID("9f3a7c1e-0000-4000-8000-000000000001")


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


def get_user_listens(user, min_ts=None, max_ts=None, count=LISTENS_DEFAULT_COUNT):
    """Build the payload for ``GET /1/user/<name>/listens``.

    Multi-scrobbler fetches this to deduplicate before submitting. The
    return value is the inner ``payload`` object; the view wraps it as
    ``{"payload": ...}``. Listens are newest-first, matching ListenBrainz.

    ``min_ts``/``max_ts`` are Unix seconds. ListenBrainz semantics:
    return listens strictly newer than ``min_ts`` and strictly older
    than ``max_ts``.
    """
    count = max(1, min(int(count), LISTENS_MAX_COUNT))

    qs = Play.objects.filter(user=user)
    if max_ts is not None:
        qs = qs.filter(played_at__lt=datetime.fromtimestamp(max_ts, tz=UTC))
    if min_ts is not None:
        qs = qs.filter(played_at__gt=datetime.fromtimestamp(min_ts, tz=UTC))

    rows = list(qs.order_by("-played_at")[:count])

    listens = []
    for play in rows:
        ts = int(play.played_at.timestamp())
        listens.append(
            {
                "user_name": user.username,
                "inserted_at": ts,
                "listened_at": ts,
                "recording_msid": str(
                    uuid.uuid5(_LISTEN_MSID_NS, str(play.id)),
                ),
                "track_metadata": {
                    "artist_name": play.artist,
                    "track_name": play.title,
                    "release_name": play.album,
                    "additional_info": {},
                },
            },
        )

    bounds = (
        Play.objects.filter(user=user)
        .order_by("played_at")
        .values_list("played_at", flat=True)
    )
    oldest = bounds.first()
    latest = bounds.last()

    return {
        "count": len(listens),
        "user_id": user.username,
        "latest_listen_ts": int(latest.timestamp()) if latest else 0,
        "oldest_listen_ts": int(oldest.timestamp()) if oldest else 0,
        "listens": listens,
    }


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
