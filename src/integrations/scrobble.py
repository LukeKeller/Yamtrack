"""ListenBrainz-compatible scrobble receiver.

Multi-scrobbler (and similar tools) send listens via the ListenBrainz API
v1 protocol. Yamtrack accepts those listens here, maps them to ``Item``
(and, when possible, ``Track``) rows by a normalized (artist, title,
album) match, and writes ``Play`` rows.

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
import re
import unicodedata
import uuid
from datetime import UTC, datetime

from django.db.models import Q
from django.utils import timezone

from app.models import Item, MediaTypes, Play, PlaySource, Track

logger = logging.getLogger(__name__)

LISTEN_TYPES_PERSIST = {"single", "import"}
LISTEN_TYPES_IGNORE = {"playing_now"}

LISTENS_DEFAULT_COUNT = 25
LISTENS_MAX_COUNT = 1000

# Fixed namespace so a given Play always yields the same recording_msid.
_LISTEN_MSID_NS = uuid.UUID("9f3a7c1e-0000-4000-8000-000000000001")

# Tokens too generic to disambiguate an artist on their own.
_ARTIST_STOPWORDS = {"the", "and", "a", "an", "of"}
_PARENS_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")
_FEAT_RE = re.compile(
    r"\b(?:feat|featuring|ft|with|w)\b.*$",
)
_ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|/|;|\bvs\b|\bx\b|&|\band\b|\bfeat\b)\s*")
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")
_MIN_SUBSTR = 4


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
        _queue_enrichment(len(plays))

    logger.info(
        "Persisted %s ListenBrainz listens (out of %s) for user %s",
        len(plays),
        len(payload),
        user.username,
    )
    return len(plays)


def _queue_enrichment(count):
    """Best-effort: queue MusicBrainz enrichment for the new Plays.

    Imported lazily and guarded so a missing/broken Celery worker can
    never break scrobble ingestion (multi-scrobbler must keep working).
    """
    try:
        from integrations.tasks import enrich_scrobble_mbids  # noqa: PLC0415

        enrich_scrobble_mbids.delay(limit=max(count, 50))
    except Exception:
        logger.exception("Could not queue scrobble MBID enrichment")


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

    item, track = match_play(artist, title, album)

    return Play(
        user=user,
        item=item,
        track=track,
        artist=artist,
        title=title,
        album=album,
        played_at=listened_at,
        duration_seconds=duration_seconds,
        source=PlaySource.LISTENBRAINZ.value,
        side=track.side if track else "",
    )


def _parse_listened_at(value):
    """Parse a ListenBrainz ``listened_at`` (Unix seconds) into a datetime."""
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    return timezone.now()


def _norm(value):
    """Normalize a free-text music string for fuzzy comparison.

    Folds accents (so "RÜFÜS" == "RUFUS", "También" == "Tambien"),
    lowercases, drops parenthetical/bracketed asides ("(Deluxe Edition)",
    "[Remastered]", Discogs "(2)" disambiguation), strips a trailing
    "feat. ..." credit, normalizes "&" to "and", reduces to
    alphanumerics, and drops a leading "the".
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = text.encode("ascii", "ignore").decode("ascii").lower().strip()
    text = _PARENS_RE.sub(" ", text)
    text = _FEAT_RE.sub(" ", text)
    text = text.replace("&", " and ")
    text = _NONALNUM_RE.sub(" ", text).strip()
    if text.startswith("the "):
        text = text[4:]
    return re.sub(r"\s+", " ", text).strip()


def _artist_keys(value):
    """Return the set of normalized artist forms for ``value``.

    Includes the whole normalized credit plus each split part for
    multi-artist credits ("A & B feat. C" -> {"a and b", "a", "b"}).
    """
    base = _norm(value)
    if not base:
        return set()
    keys = {base}
    for chunk in _ARTIST_SPLIT_RE.split(base):
        chunk = chunk.strip()
        if chunk:
            keys.add(chunk)
    return keys


def _artist_match(a_keys, b_keys):
    """True if two artist key sets refer to the same artist.

    Direct overlap, or one credit's significant tokens are a subset of
    the other's (handles "the strokes" vs "strokes", extra feat. names).
    """
    if not a_keys or not b_keys:
        return False
    if a_keys & b_keys:
        return True
    for a in a_keys:
        a_tokens = {t for t in a.split() if t not in _ARTIST_STOPWORDS}
        if not a_tokens:
            continue
        for b in b_keys:
            b_tokens = {t for t in b.split() if t not in _ARTIST_STOPWORDS}
            if b_tokens and (a_tokens <= b_tokens or b_tokens <= a_tokens):
                return True
    return False


def _text_match(a, b):
    """Loose equality for normalized titles/albums.

    Equal, or the shorter (>= 4 chars) is contained in the longer — so
    "is this it" matches a record stored as "the strokes - is this it".
    """
    if not a or not b:
        return False
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
    return len(shorter) >= _MIN_SUBSTR and shorter in longer


def _candidate_records(artist_keys):
    """RECORD Items plausibly by this artist, prefiltered in SQL.

    Uses an ``artist__icontains`` OR over the longest significant tokens
    to keep the working set small; falls back to scanning all RECORD
    Items when the prefilter finds nothing (e.g. accented artist names
    that can't be folded in SQL). Vinyl collections are small enough
    that the fallback is cheap.
    """
    tokens = sorted(
        {
            tok
            for key in artist_keys
            for tok in key.split()
            if len(tok) > 2 and tok not in _ARTIST_STOPWORDS
        },
        key=len,
        reverse=True,
    )
    base = Item.objects.filter(media_type=MediaTypes.RECORD.value).only(
        "id",
        "artist",
        "title",
    )
    if tokens:
        query = Q()
        for tok in tokens[:4]:
            query |= Q(artist__icontains=tok)
        prefiltered = list(base.filter(query))
        if prefiltered:
            return prefiltered
    return list(base)


def _match(artist, title, album):
    """Resolve a scrobble to ``(Item | None, Track | None)``.

    Order of preference:
      1. A Track on a same-artist record whose title matches -> links
         both the record Item and the Track.
      2. A same-artist record whose title matches the album.
      3. A same-artist record whose title matches the track (singles,
         and Discogs records stored as "Artist - Song").
    """
    if not artist:
        return None, None

    a_keys = _artist_keys(artist)
    if not a_keys:
        return None, None
    n_title = _norm(title)
    n_album = _norm(album)

    records = [
        r for r in _candidate_records(a_keys) if _artist_match(a_keys, _artist_keys(r.artist))
    ]
    if not records:
        return None, None
    by_id = {r.id: r for r in records}

    if n_title:
        tracks = Track.objects.filter(record_item_id__in=by_id).only(
            "id",
            "record_item_id",
            "title",
            "artist",
            "side",
        )
        for track in tracks:
            if _norm(track.title) != n_title:
                continue
            record = by_id[track.record_item_id]
            if (
                not track.artist
                or _artist_match(a_keys, _artist_keys(track.artist))
                or _artist_match(a_keys, _artist_keys(record.artist))
            ):
                return record, track

    if n_album:
        for record in records:
            if _text_match(_norm(record.title), n_album):
                return record, None

    if n_title:
        for record in records:
            if _text_match(_norm(record.title), n_title):
                return record, None

    return None, None


def match_play(artist, title, album=""):
    """Resolve a scrobble to ``(Item | None, Track | None)``."""
    return _match(artist, title, album)


def match_item(artist, title, album=""):
    """Resolve a scrobble to an ``Item`` (or ``None``).

    Back-compat entry point for the CSV scrobble importer, which only
    stores ``Play.item``. New callers should prefer ``match_play`` so
    ``Play.track`` is populated too.
    """
    item, _track = _match(artist, title, album)
    return item
