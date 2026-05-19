from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes, Sources


class BrowseViewTests(TestCase):
    """Test the browse view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.providers.tmdb.browse")
    def test_browse_defaults_to_popular_movies(self, mock_browse):
        """The browse view defaults to popular movies."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "238",
                    "title": "Test Movie",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/image.jpg",
                },
            ],
        }

        response = self.client.get(reverse("browse"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/browse.html")
        mock_browse.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "popular",
            1,
            self.user.watch_provider_region,
        )

    @patch("app.providers.tmdb.browse")
    def test_browse_tv_category(self, mock_browse):
        """The browse view passes through media type and category."""
        mock_browse.return_value = {
            "page": 2,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(
            reverse("browse") + "?media_type=tv&category=on_the_air&page=2",
        )

        self.assertEqual(response.status_code, 200)
        mock_browse.assert_called_once_with(
            MediaTypes.TV.value,
            "on_the_air",
            2,
            self.user.watch_provider_region,
        )

    @patch("app.providers.tmdb.browse")
    def test_browse_list_layout_renders(self, mock_browse):
        """The list layout renders populated results without error."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "238",
                    "title": "Test Movie",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/image.jpg",
                },
            ],
        }

        response = self.client.get(reverse("browse") + "?layout=list")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Movie")

    @patch("app.providers.tmdb.browse")
    def test_browse_invalid_inputs_fall_back(self, mock_browse):
        """Unknown media type / category fall back to popular movies."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(
            reverse("browse") + "?media_type=bogus&category=bogus",
        )

        self.assertEqual(response.status_code, 200)
        mock_browse.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "popular",
            1,
            self.user.watch_provider_region,
        )
