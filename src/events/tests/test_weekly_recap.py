from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.mixins import disable_fetch_releases
from app.models import Item, MediaTypes, Movie, Sources, Status
from events import notifications


class WeeklyRecapTests(TestCase):
    """events.notifications weekly recap."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def _finish_movie(self, media_id, days_ago):
        """Create a movie marked completed ``days_ago`` days ago.

        Status/end_date are set via ``update`` to skip the metadata-fetch in
        ``process_status`` (no network in tests).
        """
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {media_id}",
            image="http://example.com/i.jpg",
        )
        with disable_fetch_releases():
            movie = Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )
        Movie.objects.filter(pk=movie.pk).update(
            status=Status.COMPLETED.value,
            end_date=timezone.now() - timezone.timedelta(days=days_ago),
        )
        return movie

    def test_build_counts_recent_finishes(self):
        """Only finishes within the 7-day window are counted."""
        self._finish_movie("1", days_ago=2)
        self._finish_movie("2", days_ago=3)
        self._finish_movie("3", days_ago=30)  # outside window

        now = timezone.now()
        recap = notifications.build_weekly_recap(
            self.user,
            now - timezone.timedelta(days=7),
            now,
        )
        self.assertEqual(recap["finished"], 2)
        self.assertEqual(len(recap["titles"]), 2)

    def test_format_body(self):
        """The recap body mentions the finish count."""
        body = notifications.format_weekly_recap(
            {"finished": 2, "episodes": 5, "titles": ["A", "B"]},
        )
        self.assertIn("2 finished", body)
        self.assertIn("5 episodes", body)

    def test_no_opted_in_users(self):
        """Nothing happens when no users opted in."""
        result = notifications.send_weekly_recap()
        self.assertEqual(result, "No users with weekly recap enabled")

    @patch("events.notifications._send_recap_push")
    @patch("events.notifications.send_user_notification")
    def test_send_skips_empty_week(self, mock_notify, _mock_push):
        """A user who finished nothing gets no recap."""
        self.user.weekly_recap_enabled = True
        self.user.notification_urls = "json://localhost"
        self.user.save()

        result = notifications.send_weekly_recap()
        self.assertEqual(result, "Weekly recap sent to 0 users")
        mock_notify.assert_not_called()

    @patch("events.notifications._send_recap_push")
    @patch("events.notifications.send_user_notification")
    def test_send_delivers_when_active(self, mock_notify, _mock_push):
        """A user with a finish this week gets one recap notification."""
        self.user.weekly_recap_enabled = True
        self.user.notification_urls = "json://localhost"
        self.user.save()
        self._finish_movie("1", days_ago=1)

        result = notifications.send_weekly_recap()
        self.assertEqual(result, "Weekly recap sent to 1 users")
        mock_notify.assert_called_once()
