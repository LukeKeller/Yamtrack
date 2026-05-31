from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes


class SidebarViewTests(TestCase):
    """Tests for the sidebar view."""

    def setUp(self):
        """Create user for the tests."""
        self.watch_regions_patcher = patch(
            "users.views.tmdb.watch_provider_regions",
            return_value=[("UNSET", "Disabled"), ("US", "United States")],
        )
        self.watch_regions_patcher.start()
        self.addCleanup(self.watch_regions_patcher.stop)

        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_preferences_get(self):
        """Test GET request to preferences view."""
        response = self.client.get(reverse("preferences"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/preferences.html")

        self.assertIn("media_types", response.context)
        self.assertIn(MediaTypes.TV.value, response.context["media_types"])
        self.assertIn(MediaTypes.MOVIE.value, response.context["media_types"])
        self.assertNotIn(MediaTypes.EPISODE.value, response.context["media_types"])

    def test_sidebar_post_update_preferences(self):
        """Test POST request to update preferences."""
        self.user.tv_enabled = True
        self.user.movie_enabled = True
        self.user.anime_enabled = True
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "media_types_checkboxes": [MediaTypes.TV.value, MediaTypes.ANIME.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.tv_enabled)
        self.assertFalse(self.user.movie_enabled)
        self.assertTrue(self.user.anime_enabled)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Settings updated", str(messages[0]))

    def test_sidebar_post_demo_user(self):
        """Test POST request from a demo user to preferences."""
        self.user.is_demo = True
        self.user.tv_enabled = True
        self.user.movie_enabled = False
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "media_types_checkboxes": [MediaTypes.TV.value, MediaTypes.MOVIE.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.tv_enabled)
        self.assertFalse(self.user.movie_enabled)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("view-only for demo accounts", str(messages[0]))

    def test_obfuscate_unseen_episodes_post_enable(self):
        """Test enabling obfuscate_unseen_episodes via preferences."""
        self.user.obfuscate_unseen_episodes = False
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "obfuscate_unseen_episodes": "on",
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.obfuscate_unseen_episodes)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Settings updated", str(messages[0]))

    def test_obfuscate_unseen_episodes_post_disable(self):
        """Test disabling obfuscate_unseen_episodes via preferences."""
        self.user.obfuscate_unseen_episodes = True
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertFalse(self.user.obfuscate_unseen_episodes)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Settings updated", str(messages[0]))

    def test_clickable_media_cards_and_obfuscate_unseen_episodes(self):
        """Test updating both clickable_media_cards and obfuscate_unseen_episodes."""
        self.user.clickable_media_cards = False
        self.user.obfuscate_unseen_episodes = False
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "clickable_media_cards": "on",
                "obfuscate_unseen_episodes": "on",
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.clickable_media_cards)
        self.assertTrue(self.user.obfuscate_unseen_episodes)

    def test_obfuscate_unseen_episodes_post_demo_user(self):
        """Test that demo users cannot update obfuscate_unseen_episodes."""
        self.user.is_demo = True
        self.user.obfuscate_unseen_episodes = False
        self.user.save()

        response = self.client.post(
            reverse("preferences"),
            {
                "obfuscate_unseen_episodes": "on",
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))

        self.user.refresh_from_db()
        self.assertFalse(self.user.obfuscate_unseen_episodes)

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("view-only for demo accounts", str(messages[0]))

    def test_eink_mode_default_is_auto(self):
        """New users default to auto e-ink detection."""
        self.assertEqual(self.user.eink_mode, "auto")

    def test_preferences_exposes_appearance_choices(self):
        """Theme/font/eink choices are available to the preferences template."""
        response = self.client.get(reverse("preferences"))
        self.assertIn("theme_choices", response.context)
        self.assertIn("eink_choices", response.context)
        theme_values = [value for value, _ in response.context["theme_choices"]]
        self.assertIn("one-dark", theme_values)
        self.assertIn("kanagawa", theme_values)

    def test_base_renders_per_device_appearance_hooks(self):
        """Base layout carries account defaults + the device-override script."""
        response = self.client.get(reverse("preferences"))
        content = response.content.decode()
        # Account defaults are mirrored so the client script can fall back to
        # them when this device has no local override.
        self.assertIn("data-account-theme=", content)
        self.assertIn("data-account-eink=", content)
        # The localStorage-backed override API runs inline before first paint.
        self.assertIn("window.yamtrackAppearance", content)

    def test_preferences_renders_device_override_panel(self):
        """Preferences exposes the per-device theme + e-ink override controls."""
        response = self.client.get(reverse("preferences"))
        content = response.content.decode()
        self.assertIn("This device", content)
        self.assertIn("Use account default", content)

    def test_preferences_post_persists_eink_mode(self):
        """E-ink mode saves through the preferences form."""
        response = self.client.post(
            reverse("preferences"),
            {
                "eink_mode": "on",
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.eink_mode, "on")

    def test_preferences_post_rejects_invalid_eink_mode(self):
        """An out-of-range e-ink value is ignored, keeping the prior choice."""
        self.user.eink_mode = "on"
        self.user.save()
        self.client.post(
            reverse("preferences"),
            {
                "eink_mode": "bogus",
                "media_types_checkboxes": [MediaTypes.TV.value],
            },
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.eink_mode, "on")

    def test_set_eink_mode_endpoint_persists(self):
        """The header quick-toggle endpoint saves a valid mode and 204s."""
        response = self.client.post(reverse("set_eink_mode"), {"eink_mode": "on"})
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.eink_mode, "on")

    def test_set_eink_mode_endpoint_ignores_invalid(self):
        """An invalid mode leaves the stored value untouched."""
        self.user.eink_mode = "off"
        self.user.save()
        response = self.client.post(reverse("set_eink_mode"), {"eink_mode": "nope"})
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.eink_mode, "off")

    def test_set_eink_mode_endpoint_rejects_get(self):
        """The quick-toggle endpoint is POST-only."""
        response = self.client.get(reverse("set_eink_mode"))
        self.assertEqual(response.status_code, 405)

    def test_set_eink_mode_endpoint_demo_user_noop(self):
        """Demo users can't change the e-ink mode."""
        self.user.is_demo = True
        self.user.eink_mode = "off"
        self.user.save()
        response = self.client.post(reverse("set_eink_mode"), {"eink_mode": "on"})
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.eink_mode, "off")
