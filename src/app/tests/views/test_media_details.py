from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    MediaTypes,
    Sources,
    Status,
)
from app.views import _reading_projection


class MediaDetailsViewTests(TestCase):
    """Test the media details views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.providers.services.get_media_metadata")
    def test_media_details_view(self, mock_get_metadata):
        """Test the media details view."""
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "http://example.com/image.jpg",
            "overview": "Test overview",
            "release_date": "2023-01-01",
        }

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_details.html")

        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"]["title"], "Test Movie")

        mock_get_metadata.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "238",
            Sources.TMDB.value,
        )

    @patch("app.providers.services.get_media_metadata")
    @patch("app.providers.tmdb.process_episodes")
    def test_season_details_view(self, mock_process_episodes, mock_get_metadata):
        """Test the season details view."""
        mock_get_metadata.return_value = {
            "title": "Test TV Show",
            "media_id": "1668",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "image": "http://example.com/image.jpg",
            "season/1": {
                "title": "Season 1",
                "media_id": "1668",
                "media_type": MediaTypes.SEASON.value,
                "source": Sources.TMDB.value,
                "image": "http://example.com/season.jpg",
                "episodes": [],
            },
        }

        mock_process_episodes.return_value = [
            {
                "media_id": "1668",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.EPISODE.value,
                "season_number": 1,
                "episode_number": 1,
                "name": "Episode 1",
                "air_date": "2023-01-01",
                "watched": False,
            },
        ]

        response = self.client.get(
            reverse(
                "season_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_id": "1668",
                    "title": "test-tv-show",
                    "season_number": 1,
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_details.html")

        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"]["title"], "Season 1")
        self.assertEqual(len(response.context["media"]["episodes"]), 1)

        mock_get_metadata.assert_called_once_with(
            "tv_with_seasons",
            "1668",
            Sources.TMDB.value,
            [1],
        )


class ReadingProjectionTests(TestCase):
    """``_reading_projection`` extrapolates pace to a finish date."""

    @staticmethod
    def _session(days_ago, percent_start):
        return SimpleNamespace(
            start=timezone.now() - timedelta(days=days_ago),
            percent_start=percent_start,
        )

    @staticmethod
    def _book(status=Status.IN_PROGRESS.value, progress=275):
        return SimpleNamespace(status=status, progress=progress)

    def test_pace_and_finish_date_are_projected(self):
        """20% -> 55% over 7 days projects ~9 days and ~25 pages/day."""
        sessions = [self._session(0, 0.55), self._session(7, 0.20)]
        projection = _reading_projection(sessions, 55.0, self._book())

        self.assertIsNotNone(projection)
        self.assertEqual(projection["days_left"], 9)
        # progress 275 pages at 55% => 500-page book, 5%/day => 25 pages/day.
        self.assertEqual(projection["pace_pages_per_day"], 25)
        self.assertGreater(projection["projected_finish"], timezone.now())

    def test_completed_book_has_no_projection(self):
        """Only in-progress books get a projection."""
        sessions = [self._session(0, 0.55), self._session(7, 0.20)]
        projection = _reading_projection(
            sessions,
            55.0,
            self._book(status=Status.COMPLETED.value),
        )
        self.assertIsNone(projection)

    def test_near_finished_book_has_no_projection(self):
        """A book past the completion floor isn't projected."""
        sessions = [self._session(0, 0.99), self._session(7, 0.80)]
        projection = _reading_projection(sessions, 99.0, self._book())
        self.assertIsNone(projection)

    def test_same_day_window_is_too_short(self):
        """A sub-day reading window is noise, not a pace."""
        sessions = [self._session(0, 0.50), self._session(0, 0.20)]
        projection = _reading_projection(sessions, 50.0, self._book())
        self.assertIsNone(projection)
