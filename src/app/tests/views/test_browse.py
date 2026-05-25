from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from app import taste
from app.models import DismissedItem, MediaTypes, Sources


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

    @patch("app.providers.tmdb.browse")
    def test_browse_tmdb_hidden_gems_category(self, mock_browse):
        """Hidden Gems is a valid TMDB browse category."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(
            reverse("browse") + "?media_type=movie&category=hidden_gems",
        )

        self.assertEqual(response.status_code, 200)
        mock_browse.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "hidden_gems",
            1,
            self.user.watch_provider_region,
        )

    @override_settings(TRAKT_API="dummy-trakt-key")
    @patch("app.providers.trakt.browse")
    def test_browse_trakt_source(self, mock_trakt_browse):
        """Selecting Trakt as a source dispatches to the Trakt provider."""
        mock_trakt_browse.return_value = {
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

        response = self.client.get(
            reverse("browse") + "?source=trakt&category=anticipated",
        )

        self.assertEqual(response.status_code, 200)
        mock_trakt_browse.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "anticipated",
            1,
        )

    @patch("app.providers.tmdb.browse")
    def test_browse_filters_out_dismissed_items(self, mock_browse):
        """Dismissed tiles are filtered out of browse results."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 2,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "111",
                    "title": "Keep Me",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/keep.jpg",
                },
                {
                    "media_id": "222",
                    "title": "Hide Me",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/hide.jpg",
                },
            ],
        }
        DismissedItem.objects.create(
            user=self.user,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            media_id="222",
            title="Hide Me",
        )

        response = self.client.get(reverse("browse"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Keep Me")
        self.assertNotContains(response, "Hide Me")

    def test_dismiss_item_persists_and_is_idempotent(self):
        """POSTing to dismiss_item creates a row; repeats are no-ops."""
        payload = {
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "media_id": "999",
            "title": "Not For Me",
        }
        response = self.client.post(
            reverse("dismiss_item"),
            payload,
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            DismissedItem.objects.filter(user=self.user, media_id="999").count(),
            1,
        )

        response = self.client.post(
            reverse("dismiss_item"),
            payload,
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            DismissedItem.objects.filter(user=self.user, media_id="999").count(),
            1,
        )

    @patch("app.providers.tmdb.browse")
    def test_for_you_falls_back_when_cold_start(self, mock_browse):
        """For-you category falls back to popular when user has no taste signal."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }
        response = self.client.get(
            reverse("browse") + "?category=for_you",
        )
        self.assertEqual(response.status_code, 200)
        # First (and only) call is the fallback to "popular".
        mock_browse.assert_called_with(
            MediaTypes.MOVIE.value,
            "popular",
            1,
            self.user.watch_provider_region,
        )

    @patch("app.providers.tmdb.browse")
    def test_for_you_scores_and_sorts_when_user_has_signal(self, mock_browse):
        """Once the user has rated items, For You returns scored, sorted results."""
        cache.clear()
        # Seed the taste profile directly so we can sidestep Media.save()'s
        # provider hook (it tries to fetch metadata for IN_PROGRESS /
        # COMPLETED items, which the test environment can't satisfy
        # without a live TMDB key). The cache key matches
        # taste.profile_cache_key and signals will clear it if any real
        # Media is created later — but in this test nothing else writes.
        cache.set(
            taste.profile_cache_key(self.user.id, MediaTypes.MOVIE.value),
            {
                "pos": {"Action": 5.0},
                "neg": {},
                "pos_norm": 5.0,
                "neg_norm": 0.0,
                "n_pos": 5,
                "n_neg": 0,
            },
        )

        # Candidate pool: one strong Action match, one orthogonal Drama.
        mock_browse.side_effect = lambda mt, cat, page, region: {  # noqa: ARG005
            "page": 1,
            "total_results": 2,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "9001",
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "title": "Action Match",
                    "image": "",
                    "genre_names": ["Action"],
                },
                {
                    "media_id": "9002",
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "title": "Drama Orthogonal",
                    "image": "",
                    "genre_names": ["Drama"],
                },
            ],
        }

        response = self.client.get(reverse("browse") + "?category=for_you")

        self.assertEqual(response.status_code, 200)
        # Strong match (Action) should appear before weak match (Drama).
        content = response.content.decode()
        self.assertLess(content.find("Action Match"), content.find("Drama Orthogonal"))

    def test_score_item_rewards_overlap(self):
        """Items sharing genres with the positive bag score higher."""
        profile = {
            "pos": {"Action": 5.0, "Sci-Fi": 3.0},
            "neg": {"Horror": 2.0},
            "pos_norm": (5.0**2 + 3.0**2) ** 0.5,
            "neg_norm": 2.0,
            "n_pos": 10,
            "n_neg": 2,
        }
        strong = taste.score_item(profile, ["Action", "Sci-Fi"])
        weak = taste.score_item(profile, ["Drama"])
        avoided = taste.score_item(profile, ["Horror"])
        self.assertGreater(strong, weak)
        self.assertGreater(weak, avoided)

    @patch("app.providers.tmdb.browse")
    def test_browse_default_blocks_hindi_only(self, mock_browse):
        """Default filter drops Hindi tiles, leaves everything else alone."""
        mock_browse.return_value = {
            "page": 1,
            "total_results": 4,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "1",
                    "title": "English Pick",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "",
                    "original_language": "en",
                },
                {
                    "media_id": "2",
                    "title": "Japanese Pick",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "",
                    "original_language": "ja",
                },
                {
                    "media_id": "3",
                    "title": "Korean Pick",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "",
                    "original_language": "ko",
                },
                {
                    "media_id": "4",
                    "title": "Hindi Pick",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "",
                    "original_language": "hi",
                },
            ],
        }
        response = self.client.get(reverse("browse"))
        self.assertContains(response, "English Pick")
        self.assertContains(response, "Japanese Pick")
        self.assertContains(response, "Korean Pick")
        self.assertNotContains(response, "Hindi Pick")

    @patch("app.providers.tmdb.browse")
    def test_browse_shows_hindi_when_opted_in(self, mock_browse):
        """Toggling the pref re-surfaces Hindi tiles."""
        self.user.browse_include_non_english = True
        self.user.save(update_fields=["browse_include_non_english"])
        mock_browse.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "4",
                    "title": "Hindi Pick",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "",
                    "original_language": "hi",
                },
            ],
        }
        response = self.client.get(reverse("browse"))
        self.assertContains(response, "Hindi Pick")

    def test_toggle_browse_language_flips_pref(self):
        """POST flips browse_include_non_english and redirects."""
        self.user.refresh_from_db()
        self.assertFalse(self.user.browse_include_non_english)
        self.client.post(reverse("toggle_browse_language"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.browse_include_non_english)
        self.client.post(reverse("toggle_browse_language"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.browse_include_non_english)

    def test_dismiss_item_rejects_invalid_input(self):
        """Missing required fields return 400; unknown source/type return 400."""
        response = self.client.post(reverse("dismiss_item"), {})
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            reverse("dismiss_item"),
            {
                "source": "not-a-source",
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "1",
            },
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(TRAKT_API="")
    @patch("app.providers.tmdb.browse")
    def test_browse_trakt_without_credentials_falls_back(self, mock_tmdb_browse):
        """When Trakt is unconfigured, requesting it silently falls back to TMDB."""
        mock_tmdb_browse.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(reverse("browse") + "?source=trakt")

        self.assertEqual(response.status_code, 200)
        mock_tmdb_browse.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "popular",
            1,
            self.user.watch_provider_region,
        )
