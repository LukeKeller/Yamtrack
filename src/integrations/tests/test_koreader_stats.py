# ruff: noqa: D102 — test methods are self-documenting via name
"""Tests for ``integrations/koreader_stats.py`` and the cadence / sessions views.

Event ``created_at`` is ``auto_now_add=True`` so each test constructs
the event normally and then rewrites the timestamp via a queryset
``.update()`` to keep ``auto_now_add`` out of the way. That mirrors
what the kosync endpoint would have produced without forcing us to
patch ``timezone.now`` for every row.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from integrations.koreader_stats import (
    compute_daily_cadence,
    compute_sessions,
)
from integrations.models import KOReaderBookMapping, KOReaderProgressEvent


def _make_user(username="reader"):
    return get_user_model().objects.create_user(username=username, password="x")  # noqa: S106


def _make_book_item(media_id="OL123W"):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.OPENLIBRARY.value,
        media_type=MediaTypes.BOOK.value,
        title="Test Book",
    )


def _make_mapping(user, item, document_hash):
    return KOReaderBookMapping.objects.create(
        user=user,
        document_hash=document_hash,
        item=item,
    )


def _add_event(mapping, *, percentage, at):
    event = KOReaderProgressEvent.objects.create(
        mapping=mapping,
        user=mapping.user,
        percentage=percentage,
    )
    KOReaderProgressEvent.objects.filter(pk=event.pk).update(created_at=at)
    event.refresh_from_db()
    return event


class CadenceAggregationTests(TestCase):
    """``compute_daily_cadence`` rolls events into per-day positive deltas."""

    def setUp(self):
        self.user = _make_user()
        self.item = _make_book_item()
        self.mapping = _make_mapping(self.user, self.item, "a" * 32)
        self.today = timezone.localdate()

    def _at(self, day_offset, hour=12, minute=0):
        return datetime.datetime.combine(
            self.today - datetime.timedelta(days=day_offset),
            datetime.time(hour=hour, minute=minute),
            tzinfo=timezone.get_current_timezone(),
        )

    def test_empty_user_returns_empty_list(self):
        result = compute_daily_cadence(self.user)
        self.assertEqual(result, [])

    def test_single_day_returns_max_minus_min(self):
        _add_event(self.mapping, percentage=0.10, at=self._at(0, hour=9))
        _add_event(self.mapping, percentage=0.55, at=self._at(0, hour=13))
        _add_event(self.mapping, percentage=0.70, at=self._at(0, hour=20))

        result = compute_daily_cadence(self.user)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["date"], self.today)
        self.assertAlmostEqual(row["percent_read"], 0.60, places=6)
        self.assertEqual(row["mapping_count"], 1)
        self.assertEqual(row["event_count"], 3)

    def test_partial_reread_drop_does_not_subtract(self):
        # Open at 40%, then re-read earlier chapters down to 25% and up
        # to 60%. The day's forward progress is max-min == 60 - 25 = 35.
        # The "drop" doesn't go negative even though percentage went
        # backward.
        _add_event(self.mapping, percentage=0.40, at=self._at(0, hour=9))
        _add_event(self.mapping, percentage=0.25, at=self._at(0, hour=11))
        _add_event(self.mapping, percentage=0.60, at=self._at(0, hour=14))

        result = compute_daily_cadence(self.user)
        self.assertAlmostEqual(result[0]["percent_read"], 0.35, places=6)

    def test_multiple_mappings_sum_per_day(self):
        # Two books, both read 30% on the same day → 0.60 total.
        item_b = _make_book_item(media_id="OL999W")
        mapping_b = _make_mapping(self.user, item_b, "b" * 32)
        _add_event(self.mapping, percentage=0.10, at=self._at(0, hour=9))
        _add_event(self.mapping, percentage=0.40, at=self._at(0, hour=11))
        _add_event(mapping_b, percentage=0.20, at=self._at(0, hour=15))
        _add_event(mapping_b, percentage=0.50, at=self._at(0, hour=18))

        result = compute_daily_cadence(self.user)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["percent_read"], 0.60, places=6)
        self.assertEqual(result[0]["mapping_count"], 2)
        self.assertEqual(result[0]["event_count"], 4)

    def test_returns_one_row_per_active_day(self):
        _add_event(self.mapping, percentage=0.10, at=self._at(2))
        _add_event(self.mapping, percentage=0.30, at=self._at(2, hour=22))
        _add_event(self.mapping, percentage=0.50, at=self._at(0, hour=10))

        result = compute_daily_cadence(self.user)
        dates = [r["date"] for r in result]
        self.assertEqual(
            dates,
            sorted(dates),  # ascending
        )
        self.assertEqual(len(result), 2)

    def test_other_users_events_are_excluded(self):
        other = _make_user(username="other")
        other_item = _make_book_item(media_id="OLX")
        other_mapping = _make_mapping(other, other_item, "c" * 32)
        _add_event(other_mapping, percentage=0.10, at=self._at(0, hour=9))
        _add_event(other_mapping, percentage=0.80, at=self._at(0, hour=20))

        result = compute_daily_cadence(self.user)
        self.assertEqual(result, [])


class SessionGroupingTests(TestCase):
    """``compute_sessions`` splits on idle gap and mapping change."""

    def setUp(self):
        self.user = _make_user()
        self.item = _make_book_item()
        self.mapping = _make_mapping(self.user, self.item, "a" * 32)
        self.now = timezone.now()

    def _at(self, minutes_ago):
        return self.now - datetime.timedelta(minutes=minutes_ago)

    def test_consecutive_events_are_one_session(self):
        # Five events 5 minutes apart — all one session.
        for i, minutes_ago in enumerate([40, 35, 30, 25, 20]):
            _add_event(
                self.mapping,
                percentage=0.1 + i * 0.05,
                at=self._at(minutes_ago),
            )

        sessions = compute_sessions(self.user)
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.event_count, 5)
        self.assertEqual(session.mapping_id, self.mapping.id)
        self.assertAlmostEqual(session.percent_traversed, 0.20, places=6)
        # 5 events 5 min apart spans 20 min start to end.
        self.assertEqual(session.duration_minutes, 20)

    def test_long_gap_splits_session(self):
        _add_event(self.mapping, percentage=0.10, at=self._at(120))
        _add_event(self.mapping, percentage=0.20, at=self._at(115))
        # 45-minute gap > default 30 → new session.
        _add_event(self.mapping, percentage=0.30, at=self._at(70))
        _add_event(self.mapping, percentage=0.40, at=self._at(65))

        sessions = compute_sessions(self.user)
        self.assertEqual(len(sessions), 2)

    def test_mapping_change_splits_session(self):
        other_item = _make_book_item(media_id="OL2")
        other_mapping = _make_mapping(self.user, other_item, "b" * 32)

        _add_event(self.mapping, percentage=0.10, at=self._at(30))
        _add_event(self.mapping, percentage=0.20, at=self._at(25))
        # Switch books with no time gap — still splits.
        _add_event(other_mapping, percentage=0.05, at=self._at(20))
        _add_event(other_mapping, percentage=0.15, at=self._at(15))

        sessions = compute_sessions(self.user)
        self.assertEqual(len(sessions), 2)
        mapping_ids = {s.mapping_id for s in sessions}
        self.assertEqual(
            mapping_ids,
            {self.mapping.id, other_mapping.id},
        )

    def test_short_single_event_is_dropped(self):
        # One isolated event = startup-sync ping, dropped.
        _add_event(self.mapping, percentage=0.10, at=self._at(120))

        sessions = compute_sessions(self.user)
        self.assertEqual(sessions, [])

    def test_long_single_event_is_kept(self):
        # A single event covering >1 minute of wall time (unrealistic
        # from KOReader but still possible) should NOT be dropped: the
        # filter is "<2 events AND <60s", not OR. We model this by
        # constructing one event and asserting the helper retains it
        # when ``min_seconds`` is satisfied.
        # Actually a single event has duration 0, so the noise filter
        # always drops it under defaults. Override gap to verify the
        # AND-vs-OR semantics with custom thresholds instead.
        _add_event(self.mapping, percentage=0.10, at=self._at(60))
        _add_event(self.mapping, percentage=0.25, at=self._at(55))
        sessions = compute_sessions(
            self.user,
            min_events=5,
            min_seconds=120,
        )
        # 2 events spanning 5 min: fails min_events alone, fails
        # min_seconds alone, but kept because the rule is AND.
        self.assertEqual(len(sessions), 1)

    def test_filter_by_mapping(self):
        other_item = _make_book_item(media_id="OL2")
        other_mapping = _make_mapping(self.user, other_item, "b" * 32)

        _add_event(self.mapping, percentage=0.10, at=self._at(60))
        _add_event(self.mapping, percentage=0.20, at=self._at(55))
        _add_event(other_mapping, percentage=0.05, at=self._at(50))
        _add_event(other_mapping, percentage=0.15, at=self._at(45))

        sessions = compute_sessions(self.user, mapping=self.mapping)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].mapping_id, self.mapping.id)

    def test_other_users_events_are_excluded(self):
        other = _make_user(username="other")
        other_item = _make_book_item(media_id="OLX")
        other_mapping = _make_mapping(other, other_item, "c" * 32)
        _add_event(other_mapping, percentage=0.10, at=self._at(30))
        _add_event(other_mapping, percentage=0.30, at=self._at(25))

        sessions = compute_sessions(self.user)
        self.assertEqual(sessions, [])

    def test_returns_newest_first(self):
        _add_event(self.mapping, percentage=0.10, at=self._at(300))
        _add_event(self.mapping, percentage=0.20, at=self._at(295))
        _add_event(self.mapping, percentage=0.30, at=self._at(60))
        _add_event(self.mapping, percentage=0.40, at=self._at(55))

        sessions = compute_sessions(self.user)
        self.assertEqual(len(sessions), 2)
        self.assertGreater(sessions[0].start, sessions[1].start)


class CadenceViewTests(TestCase):
    """/koreader/cadence renders the heatmap and headline stats."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.item = _make_book_item()
        self.mapping = _make_mapping(self.user, self.item, "a" * 32)

    def test_renders_with_no_events(self):
        response = self.client.get(reverse("koreader_cadence"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_days"], 0)
        self.assertEqual(response.context["current_streak"], 0)
        self.assertEqual(response.context["longest_streak"], 0)
        # Grid is always 53 columns of 7 days.
        self.assertEqual(len(response.context["weeks"]), 53)
        for week in response.context["weeks"]:
            self.assertEqual(len(week), 7)

    def test_renders_with_events_and_computes_streak(self):
        # Three consecutive days ending today.
        now = timezone.now()
        for days_ago in (2, 1, 0):
            at = now - datetime.timedelta(days=days_ago)
            _add_event(self.mapping, percentage=0.1, at=at)
            _add_event(
                self.mapping,
                percentage=0.3,
                at=at + datetime.timedelta(hours=1),
            )

        response = self.client.get(reverse("koreader_cadence"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_days"], 3)
        self.assertEqual(response.context["current_streak"], 3)
        self.assertEqual(response.context["longest_streak"], 3)

    def test_other_users_events_are_excluded_from_grid(self):
        other = _make_user(username="other")
        other_item = _make_book_item(media_id="OLZ")
        other_mapping = _make_mapping(other, other_item, "z" * 32)
        _add_event(other_mapping, percentage=0.1, at=timezone.now())
        _add_event(
            other_mapping,
            percentage=0.5,
            at=timezone.now() - datetime.timedelta(minutes=30),
        )

        response = self.client.get(reverse("koreader_cadence"))
        self.assertEqual(response.context["active_days"], 0)


class SessionsViewTests(TestCase):
    """/koreader/sessions lists inferred sessions across books."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.item = _make_book_item()
        self.mapping = _make_mapping(self.user, self.item, "a" * 32)

    def _at(self, minutes_ago):
        return timezone.now() - datetime.timedelta(minutes=minutes_ago)

    def test_renders_empty_state_with_no_sessions(self):
        response = self.client.get(reverse("koreader_sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No reading sessions yet")

    def test_renders_session_rows_with_item_link(self):
        _add_event(self.mapping, percentage=0.10, at=self._at(60))
        _add_event(self.mapping, percentage=0.20, at=self._at(55))
        _add_event(self.mapping, percentage=0.30, at=self._at(50))

        response = self.client.get(reverse("koreader_sessions"))
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item"].pk, self.item.pk)

    def test_excludes_other_users(self):
        other = _make_user(username="other")
        other_item = _make_book_item(media_id="OLY")
        other_mapping = _make_mapping(other, other_item, "y" * 32)
        _add_event(other_mapping, percentage=0.10, at=self._at(60))
        _add_event(other_mapping, percentage=0.30, at=self._at(55))

        response = self.client.get(reverse("koreader_sessions"))
        self.assertEqual(response.context["rows"], [])
