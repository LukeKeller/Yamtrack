"""Derived statistics over the ``KOReaderProgressEvent`` log.

Two computations live here, both pure functions of the event log:

* :func:`compute_daily_cadence` — for each calendar day in a window,
  how much of "a book" the user actually read that day. Computed as
  the sum across mappings of ``max(percentage) - min(percentage)`` on
  that day, clamped to positive deltas so a re-read that drops
  percentage doesn't subtract from the day's total. (One unit = one
  whole book; 0.5 = half a book's progress made that day, summed
  across whichever titles were active.)

* :func:`compute_sessions` — group consecutive events for a user into
  inferred reading sessions, split on either ``gap > GAP_MINUTES`` or
  a change of mapping (a different book = a different session, even
  if back-to-back). Short / single-event sessions are dropped because
  KOReader emits a startup-sync ping per book on open.

Neither of these touches Book/Item directly — they read from the
denormalised ``user`` FK on the event log so heavy users don't have
to pay for the mapping join just to render the cadence heatmap.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass

from django.utils import timezone

from integrations.models import KOReaderProgressEvent

DEFAULT_SESSION_GAP_MINUTES = 30
DEFAULT_MIN_SESSION_SECONDS = 60
DEFAULT_MIN_SESSION_EVENTS = 2
CADENCE_WINDOW_DAYS = 371  # 53 weeks, enough for the contribution grid


def compute_daily_cadence(user, *, since=None, until=None):
    """Per-day reading totals for ``user``.

    Returns a list of ``{date, percent_read, mapping_count, event_count}``
    ordered ascending by date. ``percent_read`` is the sum across
    mappings active that day of ``max(percentage) - min(percentage)``,
    so it counts only forward progress (KOReader can push lower
    percentages on a partial re-read; those don't subtract from the
    day's total).

    Days with no events are omitted — the caller fills them in for
    rendering (an empty heatmap cell is cheaper than carrying ~365
    zero-rows through the template).

    ``since``/``until`` default to the last ``CADENCE_WINDOW_DAYS``
    ending today (server-local date — Django's ``USE_TZ=True`` means
    ``timezone.localdate()`` is the right "today").
    """
    if until is None:
        until = timezone.localdate()
    if since is None:
        since = until - datetime.timedelta(days=CADENCE_WINDOW_DAYS - 1)

    events = (
        KOReaderProgressEvent.objects.filter(
            user=user,
            created_at__date__gte=since,
            created_at__date__lte=until,
        )
        .order_by("created_at")
        .values_list("created_at", "percentage", "mapping_id")
    )

    # Per (date, mapping_id) bucket, keep min + max percentage and a
    # raw event count. One Python pass is cheap at the volumes we
    # expect (~50k events/yr/user max) and lets the day-level
    # aggregation reuse the same scan.
    by_day_mapping: dict[tuple, dict] = defaultdict(
        lambda: {"lo": None, "hi": None, "events": 0},
    )
    by_day_meta: dict = defaultdict(
        lambda: {"events": 0, "mappings": set()},
    )

    for created_at, pct, mapping_id in events:
        day = timezone.localtime(created_at).date()
        key = (day, mapping_id)
        bucket = by_day_mapping[key]
        if bucket["lo"] is None or pct < bucket["lo"]:
            bucket["lo"] = pct
        if bucket["hi"] is None or pct > bucket["hi"]:
            bucket["hi"] = pct
        bucket["events"] += 1
        meta = by_day_meta[day]
        meta["events"] += 1
        meta["mappings"].add(mapping_id)

    per_day_percent: dict = defaultdict(float)
    for (day, _mapping_id), bucket in by_day_mapping.items():
        delta = max(0.0, (bucket["hi"] or 0.0) - (bucket["lo"] or 0.0))
        per_day_percent[day] += delta

    return [
        {
            "date": day,
            "percent_read": per_day_percent[day],
            "mapping_count": len(meta["mappings"]),
            "event_count": meta["events"],
        }
        for day, meta in sorted(by_day_meta.items())
    ]


@dataclass
class ReadingSession:
    """One inferred reading session for a user.

    ``start`` / ``end`` are the timestamps of the first and last event
    in the session. ``percent_traversed`` is positive-only — a session
    that ends with a lower percentage (re-read of an earlier chapter)
    reports ``0.0`` rather than a negative number, matching the
    cadence-aggregation rule.
    """

    start: datetime.datetime
    end: datetime.datetime
    mapping_id: int
    event_count: int
    percent_start: float
    percent_end: float

    @property
    def duration_seconds(self):
        """Wall-clock duration of the session."""
        return (self.end - self.start).total_seconds()

    @property
    def duration_minutes(self):
        """Wall-clock duration in whole minutes (rounded)."""
        return round(self.duration_seconds / 60)

    @property
    def percent_traversed(self):
        """Forward progress made within the session (0.0-1.0)."""
        return max(0.0, self.percent_end - self.percent_start)

    @property
    def percent_traversed_pct(self):
        """Forward progress as a percentage (0-100) for display."""
        return self.percent_traversed * 100


def compute_sessions(
    user,
    *,
    mapping=None,
    limit=None,
    gap_minutes=DEFAULT_SESSION_GAP_MINUTES,
    min_seconds=DEFAULT_MIN_SESSION_SECONDS,
    min_events=DEFAULT_MIN_SESSION_EVENTS,
):
    """Group ``user``'s progress events into reading sessions.

    Pass ``mapping`` to restrict to one ``KOReaderBookMapping`` — the
    per-book history page does this so the panel below the chart only
    shows sessions for the current book.

    A session opens on the first event after a gap of more than
    ``gap_minutes`` or after a mapping change, and closes on the next
    such event (or on the final event of the stream). A session is
    dropped only when it's *both* too short (< ``min_seconds``) *and*
    too sparse (< ``min_events`` events) — KOReader pings the kosync
    server on book-open with a single event, so an unfiltered list is
    mostly those one-shot pings, but a long single-event session
    (e.g. one bookmark mid-read) should still show up.

    Returns ``ReadingSession`` objects newest first; pass ``limit`` to
    cap the result.
    """
    qs = KOReaderProgressEvent.objects.filter(user=user)
    if mapping is not None:
        qs = qs.filter(mapping=mapping)

    events = list(
        qs.order_by("created_at").values(
            "created_at",
            "percentage",
            "mapping_id",
        ),
    )

    gap = datetime.timedelta(minutes=gap_minutes)
    sessions: list[ReadingSession] = []
    current: ReadingSession | None = None

    def _is_noise(s):
        return s.event_count < min_events and s.duration_seconds < min_seconds

    def _close(s):
        if s is not None and not _is_noise(s):
            sessions.append(s)

    for ev in events:
        if current is None:
            current = ReadingSession(
                start=ev["created_at"],
                end=ev["created_at"],
                mapping_id=ev["mapping_id"],
                event_count=1,
                percent_start=ev["percentage"],
                percent_end=ev["percentage"],
            )
            continue

        same_book = ev["mapping_id"] == current.mapping_id
        within_gap = ev["created_at"] - current.end <= gap
        if same_book and within_gap:
            current.end = ev["created_at"]
            current.percent_end = ev["percentage"]
            current.event_count += 1
            continue

        _close(current)
        current = ReadingSession(
            start=ev["created_at"],
            end=ev["created_at"],
            mapping_id=ev["mapping_id"],
            event_count=1,
            percent_start=ev["percentage"],
            percent_end=ev["percentage"],
        )

    _close(current)
    sessions.reverse()
    if limit is not None:
        sessions = sessions[:limit]
    return sessions


def aggregate_reading_time(sessions):
    """Return ``(total_minutes, session_count, avg_minutes)`` for ``sessions``.

    ``avg_minutes`` is ``0`` when there are no sessions (avoids divide-
    by-zero in templates). Designed to be called once at view time
    with the same ``sessions`` list the template iterates over — no
    extra DB roundtrip.
    """
    minutes = sum(s.duration_minutes for s in sessions)
    count = len(sessions)
    avg = (minutes / count) if count else 0
    return minutes, count, avg
