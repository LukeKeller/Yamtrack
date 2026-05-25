from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Record, Sources, Status


class ArtistDetailsViewTests(TestCase):
    """Test the Discogs artist detail page."""

    def setUp(self):
        """Create a user, log in, and stub a tracked Record."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.owned_item = Item.objects.create(
            media_id="111",
            source=Sources.DISCOGS.value,
            media_type=MediaTypes.RECORD.value,
            title="Owned Album",
            image="http://example.com/owned.jpg",
            artist="Test Artist",
        )
        # PLANNING avoids the COMPLETED branch of process_status() which
        # otherwise calls discogs.record() to fetch max_progress.
        self.record = Record(
            user=self.user,
            item=self.owned_item,
            status=Status.PLANNING.value,
        )
        self.record._history_user = self.user
        self.record.save()

    @patch("app.providers.discogs.artist_discography")
    @patch("app.providers.discogs.artist")
    @patch("app.providers.discogs.artist_lookup")
    def test_artist_page_renders_with_owned_indicator(
        self, mock_lookup, mock_artist, mock_disco,
    ):
        """An owned release is flagged on the discography grid."""
        mock_lookup.return_value = "42"
        mock_artist.return_value = {
            "artist_id": "42",
            "name": "Test Artist",
            "image": "http://example.com/artist.jpg",
            "profile": "A test artist.",
            "source_url": "https://www.discogs.com/artist/42",
            "real_name": "",
            "name_variations": [],
            "members": [],
            "urls": [],
        }
        mock_disco.return_value = [
            {
                "media_id": "111",
                "master_id": "",
                "type": "release",
                "title": "Owned Album",
                "year": 2020,
                "image": "http://example.com/owned.jpg",
                "format": "Vinyl",
                "label": "Label A",
                "role": "Main",
            },
            {
                "media_id": "222",
                "master_id": "",
                "type": "release",
                "title": "Missing Album",
                "year": 2018,
                "image": "http://example.com/missing.jpg",
                "format": "Vinyl",
                "label": "Label B",
                "role": "Main",
            },
        ]

        response = self.client.get(
            reverse("artist_details", kwargs={"name": "Test Artist"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/artist.html")
        self.assertEqual(response.context["artist"]["name"], "Test Artist")
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(response.context["owned_count"], 1)

        releases = response.context["releases"]
        owned = [r for r in releases if r["media"] is not None]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["release"]["media_id"], "111")

    @patch("app.providers.discogs.artist_lookup")
    def test_artist_lookup_miss_returns_404(self, mock_lookup):
        """When Discogs has no artist match, the page 404s with a friendly message."""
        mock_lookup.return_value = None

        response = self.client.get(
            reverse("artist_details", kwargs={"name": "Nonexistent Band"}),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "app/artist.html")
        self.assertTrue(response.context["artist_not_found"])

    @patch("app.providers.discogs.artist_discography")
    @patch("app.providers.discogs.artist")
    @patch("app.providers.discogs.artist_lookup")
    def test_filter_owned_only(self, mock_lookup, mock_artist, mock_disco):
        """The ``filter=owned`` querystring narrows the grid to library items."""
        mock_lookup.return_value = "42"
        mock_artist.return_value = {
            "artist_id": "42",
            "name": "Test Artist",
            "image": "http://example.com/artist.jpg",
            "profile": "",
            "source_url": "https://www.discogs.com/artist/42",
            "real_name": "",
            "name_variations": [],
            "members": [],
            "urls": [],
        }
        mock_disco.return_value = [
            {
                "media_id": "111",
                "master_id": "",
                "type": "release",
                "title": "Owned Album",
                "year": 2020,
                "image": "",
                "format": "",
                "label": "",
                "role": "Main",
            },
            {
                "media_id": "222",
                "master_id": "",
                "type": "release",
                "title": "Missing Album",
                "year": 2018,
                "image": "",
                "format": "",
                "label": "",
                "role": "Main",
            },
        ]

        response = self.client.get(
            reverse("artist_details", kwargs={"name": "Test Artist"}),
            {"filter": "owned"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["releases"]), 1)
        # owned_count stays anchored to the unfiltered total
        self.assertEqual(response.context["owned_count"], 1)
