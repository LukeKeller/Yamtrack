"""One-time scrobble import from a generic CSV.

Accepts a CSV with the columns ``played_at, artist, track`` (and an
optional ``album``). Each row becomes a single :class:`app.models.Play`
with ``source = LISTENBRAINZ`` so it shows up in /music/history alongside
live scrobbles. Item matching reuses the same case-insensitive
``(artist, title)`` resolver as the live scrobble receiver, so imports
are functionally identical to having received the same listens over the
ListenBrainz endpoint.

Header names are matched case-insensitively, and a handful of common
aliases are accepted (e.g. ``timestamp``/``uts`` for ``played_at``,
``track_name`` for ``track``). This lets exports from Last.fm tools,
ListenBrainz, Maloja, etc. import without column renaming.
"""

import csv
import io
import logging
from datetime import UTC, datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import Play, PlaySource
from integrations import scrobble
from integrations.imports.helpers import (
    MediaImportError,
    MediaImportUnexpectedError,
)

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("played_at", "artist", "track")

COLUMN_ALIASES = {
    # ``uts`` first — Last.fm exports (e.g. mainstream.ghan.nl) include both
    # ``uts`` (Unix epoch) and ``utc_time`` ("09 May 2026, 17:57"). Prefer
    # the epoch because it's unambiguous and round-trips losslessly.
    "played_at": ("uts", "timestamp", "listened_at", "utc_time", "date"),
    "artist": ("artist_name",),
    "track": ("track_name", "title", "song"),
    "album": ("album_name", "release", "release_name"),
}


def importer(file, user, mode):
    """Entry point matching the existing importer signature."""
    return ScrobblesImporter(file, user, mode).import_data()


class ScrobblesImporter:
    """One-shot CSV scrobble importer."""

    def __init__(self, file, user, mode):
        """Save args; ``mode`` is accepted for parity but imports always append."""
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

    def import_data(self):  # noqa: C901
        """Parse the CSV and bulk-insert Play rows. Returns (counts, warnings)."""
        try:
            raw = self.file.read()
        except Exception as e:
            msg = "Could not read the uploaded file."
            raise MediaImportUnexpectedError(msg) from e

        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8-sig")
            except UnicodeDecodeError as e:
                msg = "File must be UTF-8 encoded."
                raise MediaImportError(msg) from e

        reader = csv.DictReader(io.StringIO(raw))
        if not reader.fieldnames:
            msg = "Empty CSV file (no header row)."
            raise MediaImportError(msg)

        field_map = self._resolve_columns(reader.fieldnames)
        missing = [c for c in REQUIRED_COLUMNS if c not in field_map]
        if missing:
            msg = (
                f"CSV is missing required columns: {', '.join(missing)}. "
                "Required: played_at, artist, track (album optional)."
            )
            raise MediaImportError(msg)

        plays = []
        skipped = 0
        for row in reader:
            artist = (row.get(field_map["artist"]) or "").strip()
            track = (row.get(field_map["track"]) or "").strip()
            played_at_raw = (row.get(field_map["played_at"]) or "").strip()
            album = ""
            if "album" in field_map:
                album = (row.get(field_map["album"]) or "").strip()

            if not (artist and track and played_at_raw):
                skipped += 1
                continue

            played_at = _parse_played_at(played_at_raw)
            if played_at is None:
                skipped += 1
                continue

            plays.append(
                Play(
                    user=self.user,
                    item=scrobble.match_item(artist, track, album),
                    artist=artist,
                    title=track,
                    album=album,
                    played_at=played_at,
                    source=PlaySource.LISTENBRAINZ.value,
                    side="",
                ),
            )

        if plays:
            Play.objects.bulk_create(plays, batch_size=500)

        logger.info(
            "Imported %s scrobble plays for user %s (skipped %s)",
            len(plays),
            self.user.username,
            skipped,
        )
        warnings = (
            f"Skipped {skipped} rows with missing or invalid data."
            if skipped
            else ""
        )
        return {"play": len(plays)}, warnings

    @staticmethod
    def _resolve_columns(fieldnames):
        """Map canonical column names to whatever the CSV's header actually uses."""
        lowered = {(name or "").strip().lower(): name for name in fieldnames}
        resolved = {}
        for canonical in (*REQUIRED_COLUMNS, "album"):
            if canonical in lowered:
                resolved[canonical] = lowered[canonical]
                continue
            for alias in COLUMN_ALIASES.get(canonical, ()):
                if alias in lowered:
                    resolved[canonical] = lowered[alias]
                    break
        return resolved


def _parse_played_at(raw):
    """Parse a played-at value into an aware datetime.

    Accepts a Unix epoch (seconds), an ISO 8601 timestamp, or any free-form
    date string that dateutil can recognize (e.g. "09 May 2026, 17:57").
    Returns ``None`` if nothing parses, in which case the row is skipped.
    """
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=UTC)
        except (ValueError, OSError):
            return None
    dt = parse_datetime(raw)
    if dt is not None:
        if dt.tzinfo is None:
            dt = timezone.make_aware(dt, UTC)
        return dt
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = None
    if dt is not None:
        if dt.tzinfo is None:
            dt = timezone.make_aware(dt, UTC)
        return dt
    # Last-resort: free-form parsing for Last.fm's "09 May 2026, 17:57" etc.
    try:
        from dateutil import parser as dateutil_parser  # noqa: PLC0415
        dt = dateutil_parser.parse(raw)
    except (ValueError, OverflowError, ImportError):
        return None
    if dt.tzinfo is None:
        dt = timezone.make_aware(dt, UTC)
    return dt
