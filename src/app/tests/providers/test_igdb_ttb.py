from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from app.providers import igdb


class IgdbTimeToBeatTests(TestCase):
    """app.providers.igdb.time_to_beat parsing + caching."""

    def setUp(self):
        """Clear the provider cache between tests."""
        cache.clear()

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_parses_seconds_into_hours(self, mock_api, _mock_token):
        """Seconds from IGDB are converted to rounded hours."""
        mock_api.return_value = [
            {
                "game_id": 1020,
                "hastily": 9000,  # 2.5h
                "normally": 18000,  # 5.0h
                "completely": 36000,  # 10.0h
                "count": 1234,
            },
        ]
        result = igdb.time_to_beat(1020)
        self.assertEqual(result["hastily"], 2.5)
        self.assertEqual(result["normally"], 5.0)
        self.assertEqual(result["completely"], 10.0)
        self.assertEqual(result["count"], 1234)

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_no_data_returns_none(self, mock_api, _mock_token):
        """An empty IGDB response yields None."""
        mock_api.return_value = []
        self.assertIsNone(igdb.time_to_beat(999999))

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_result_is_cached(self, mock_api, _mock_token):
        """A second lookup is served from cache without re-hitting IGDB."""
        mock_api.return_value = [{"game_id": 1, "normally": 3600, "count": 1}]
        igdb.time_to_beat(1)
        igdb.time_to_beat(1)
        self.assertEqual(mock_api.call_count, 1)

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_missing_buckets_are_none(self, mock_api, _mock_token):
        """Absent buckets parse to None rather than raising."""
        mock_api.return_value = [{"game_id": 1, "normally": 7200}]
        result = igdb.time_to_beat(1)
        self.assertIsNone(result["hastily"])
        self.assertEqual(result["normally"], 2.0)
        self.assertIsNone(result["completely"])
