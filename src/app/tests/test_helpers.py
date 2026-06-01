from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import TestCase, override_settings

from app.helpers import (
    build_absolute_app_url,
    enrich_items_with_user_data,
    extract_release_date,
    form_error_messages,
    get_configured_app_url,
    minutes_to_hhmm,
    redirect_back,
)
from app.models import Item, MediaTypes, Movie, Sources, Status


class HelpersTest(TestCase):
    """Test helper functions."""

    def test_minutes_to_hhmm(self):
        """Test conversion of minutes to HH:MM format."""
        # Test minutes only
        self.assertEqual(minutes_to_hhmm(30), "30min")

        # Test hours and minutes
        self.assertEqual(minutes_to_hhmm(90), "1h 30min")
        self.assertEqual(minutes_to_hhmm(125), "2h 05min")

        # Test zero
        self.assertEqual(minutes_to_hhmm(0), "0min")

    @override_settings(URLS=["https://yamtrack.example.com:8924"])
    def test_get_configured_app_url_from_urls(self):
        """Test configured public origin from URLS."""
        self.assertEqual(
            get_configured_app_url(),
            "https://yamtrack.example.com:8924",
        )

    @override_settings(URLS=["https://yamtrack.example.com"])
    def test_build_absolute_app_url_uses_configured_origin(self):
        """Test absolute URL construction behind reverse proxies."""
        request = MagicMock()

        result = build_absolute_app_url(request, "/import/trakt/private")

        self.assertEqual(result, "https://yamtrack.example.com/import/trakt/private")
        request.build_absolute_uri.assert_not_called()

    @override_settings(URLS=["https://yamtrack.example.com"], BASE_URL="/stackwise")
    def test_build_absolute_app_url_splices_base_url_subpath(self):
        """A sub-path install prefixes BASE_URL so copied links don't 302."""
        request = MagicMock()

        result = build_absolute_app_url(request, "/api/koreader")

        self.assertEqual(result, "https://yamtrack.example.com/stackwise/api/koreader")
        request.build_absolute_uri.assert_not_called()

    @override_settings(
        URLS=["https://yamtrack.example.com/stackwise"],
        BASE_URL="/stackwise",
    )
    def test_build_absolute_app_url_does_not_double_subpath(self):
        """If URLS already carries the sub-path, don't prefix it twice."""
        request = MagicMock()

        result = build_absolute_app_url(request, "/api/koreader")

        self.assertEqual(result, "https://yamtrack.example.com/stackwise/api/koreader")

    @override_settings(URLS=[])
    def test_build_absolute_app_url_falls_back_to_request(self):
        """Test request-based absolute URL construction without URLS."""
        request = MagicMock()
        request.build_absolute_uri.return_value = (
            "http://testserver/import/trakt/private"
        )

        result = build_absolute_app_url(request, "/import/trakt/private")

        self.assertEqual(result, "http://testserver/import/trakt/private")
        request.build_absolute_uri.assert_called_once_with("/import/trakt/private")

    @patch("app.helpers.url_has_allowed_host_and_scheme")
    @patch("app.helpers.HttpResponseRedirect")
    @patch("app.helpers.redirect")
    def test_redirect_back_with_next(self, _, mock_http_redirect, mock_url_check):
        """Test redirect_back with a 'next' parameter."""
        mock_url_check.return_value = True
        mock_http_redirect.return_value = "redirected"

        request = MagicMock()
        request.GET = {"next": "http://example.com/path?page=2&sort=name"}

        result = redirect_back(request)

        # Check that we redirected to the URL without the page parameter
        mock_http_redirect.assert_called_once()
        redirect_url = mock_http_redirect.call_args[0][0]
        self.assertEqual(redirect_url, "http://example.com/path?sort=name")
        self.assertEqual(result, "redirected")

    @patch("app.helpers.url_has_allowed_host_and_scheme")
    @patch("app.helpers.redirect")
    def test_redirect_back_without_next(self, mock_redirect, mock_url_check):
        """Test redirect_back without a 'next' parameter."""
        mock_url_check.return_value = False
        mock_redirect.return_value = "home_redirect"

        request = MagicMock()
        request.GET = {}

        result = redirect_back(request)

        mock_redirect.assert_called_once_with("home")
        self.assertEqual(result, "home_redirect")

    @patch("app.helpers.messages")
    def test_form_error_messages(self, mock_messages):
        """Test form_error_messages function."""
        form = MagicMock()
        form.errors = {
            "title": ["This field is required."],
            "release_date": ["Enter a valid date."],
        }
        request = HttpRequest()

        form_error_messages(form, request)

        # Check that error messages were added
        self.assertEqual(mock_messages.error.call_count, 2)
        mock_messages.error.assert_any_call(request, "Title: This field is required.")
        mock_messages.error.assert_any_call(
            request,
            "Release Date: Enter a valid date.",
        )


class ExtractReleaseDateTest(TestCase):
    """extract_release_date pulls a date out of every provider shape we use."""

    def test_tv_first_air_date(self):
        """TV metadata exposes the premiere as details.first_air_date."""
        meta = {"details": {"first_air_date": "1966-09-08"}}
        self.assertEqual(extract_release_date(meta), date(1966, 9, 8))

    def test_movie_release_date(self):
        """Movie metadata exposes the release as details.release_date."""
        meta = {"details": {"release_date": "1972-03-14"}}
        self.assertEqual(extract_release_date(meta), date(1972, 3, 14))

    def test_anime_start_date(self):
        """Anime/manga/comic metadata uses details.start_date."""
        meta = {"details": {"start_date": "2020-04-11"}}
        self.assertEqual(extract_release_date(meta), date(2020, 4, 11))

    def test_book_publish_date(self):
        """Book metadata exposes details.publish_date (year-only is fine)."""
        meta = {"details": {"publish_date": "1949"}}
        self.assertEqual(extract_release_date(meta), date(1949, 1, 1))

    def test_boardgame_year_only(self):
        """Board game metadata gives an int year — still a usable date."""
        meta = {"details": {"year": 1995}}
        self.assertEqual(extract_release_date(meta), date(1995, 1, 1))

    def test_top_level_fallback(self):
        """Some provider payloads surface the date at the root payload."""
        # e.g. tmdb.py:763 sets ``first_air_date`` on the root.
        meta = {"first_air_date": "1987-09-28"}
        self.assertEqual(extract_release_date(meta), date(1987, 9, 28))

    def test_missing(self):
        """Empty / None inputs return None rather than raising."""
        self.assertIsNone(extract_release_date({"details": {}}))
        self.assertIsNone(extract_release_date({}))
        self.assertIsNone(extract_release_date(None))


class EnrichItemsWithUserDataTest(TestCase):
    """Test the enrich_items_with_user_data function."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "test", "password": "testpass"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.request = MagicMock()
        self.request.user = self.user

        # Create test items in the database
        self.movie_item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )

        self.season_item = Item.objects.create(
            media_id="67890",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test TV Show",
            image="http://example.com/show.jpg",
            season_number=1,
        )

        # Create user tracking data for the movie
        self.movie_media = Movie.objects.create(
            item=self.movie_item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
        )

    def test_enrich_items_with_user_data(self):
        """Test enriching items with multiple scenarios."""
        raw_items = [
            # Scenario 1: Existing movie with user tracking data
            {
                "media_id": "238",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Test Movie",
                "image": "http://example.com/movie.jpg",
                "release_date": "2023-01-01",
                "rating": 8.5,
                "genre": "Action",
            },
            # Scenario 2: Existing season without user tracking data
            {
                "media_id": "67890",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.SEASON.value,
                "title": "Test TV Show",
                "season_title": "Season 1",
                "season_number": 1,
                "image": "http://example.com/show.jpg",
            },
            # Scenario 3: Non-existent item (raw data only)
            {
                "media_id": "99999",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Unknown Movie",
                "image": "http://example.com/unknown.jpg",
                "description": "This movie doesn't exist in our database",
            },
        ]

        enriched_items = enrich_items_with_user_data(self.request, raw_items, "test")
        self.assertEqual(len(enriched_items), 3)

        # Scenario 1: Existing movie with user tracking data
        movie_enriched = enriched_items[0]
        self.assertEqual(movie_enriched["media"], self.movie_media)
        self.assertEqual(movie_enriched["item"]["title"], "Test Movie")
        self.assertEqual(movie_enriched["item"]["media_id"], "238")
        # Verify additional properties are preserved
        self.assertEqual(movie_enriched["item"]["release_date"], "2023-01-01")
        self.assertEqual(movie_enriched["item"]["rating"], 8.5)
        self.assertEqual(movie_enriched["item"]["genre"], "Action")

        # Scenario 2: Existing season without user tracking data
        season_enriched = enriched_items[1]
        self.assertEqual(
            season_enriched["media"],
            None,
        )  # No user tracking for this season
        self.assertEqual(
            season_enriched["item"]["season_title"],
            "Season 1",
        )  # Should use season_title
        self.assertEqual(season_enriched["item"]["season_number"], 1)

        # Scenario 3: Non-existent movie (raw data)
        unknown_movie_enriched = enriched_items[2]
        self.assertEqual(
            unknown_movie_enriched["item"]["media_id"],
            raw_items[2]["media_id"],
        )
        self.assertEqual(unknown_movie_enriched["media"], None)
        self.assertEqual(unknown_movie_enriched["item"]["title"], "Unknown Movie")
        self.assertEqual(unknown_movie_enriched["item"]["media_id"], "99999")
        self.assertEqual(
            unknown_movie_enriched["item"]["description"],
            "This movie doesn't exist in our database",
        )

    def test_hide_completed_recommendations_enabled(self):
        """Test that completed items are hidden when preference is enabled."""
        self.user.hide_completed_recommendations = True
        self.user.save()

        raw_items = [
            {
                "media_id": "238",  # This is our completed movie
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Test Movie",
                "image": "http://example.com/movie.jpg",
            },
            {
                "media_id": "99999",  # Not tracked
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Unknown Movie",
                "image": "http://example.com/unknown.jpg",
            },
        ]

        # When section is "recommendations", completed items should be hidden
        enriched_items = enrich_items_with_user_data(
            self.request, raw_items, "recommendations"
        )
        self.assertEqual(len(enriched_items), 1)
        self.assertEqual(enriched_items[0]["item"]["media_id"], "99999")

    def test_hide_completed_recommendations_disabled(self):
        """Test that completed items are shown when preference is disabled."""
        self.user.hide_completed_recommendations = False
        self.user.save()

        raw_items = [
            {
                "media_id": "238",  # This is our completed movie
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Test Movie",
                "image": "http://example.com/movie.jpg",
            },
            {
                "media_id": "99999",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Unknown Movie",
                "image": "http://example.com/unknown.jpg",
            },
        ]

        # With preference disabled, all items should be returned
        enriched_items = enrich_items_with_user_data(
            self.request, raw_items, "recommendations"
        )
        self.assertEqual(len(enriched_items), 2)
