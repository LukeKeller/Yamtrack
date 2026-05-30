from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    DiaryEntry,
    DismissedItem,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)


class DiaryViewTests(TestCase):
    """Diary log/list/delete flows (app.models.DiaryEntry)."""

    def setUp(self):
        """Create a user, a movie item, and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Godfather",
            image="http://example.com/image.jpg",
        )

    def test_log_creates_entry(self):
        """Posting to diary_log creates a DiaryEntry for the item."""
        response = self.client.post(
            reverse("diary_log"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "logged_at": "2026-05-01",
                "score": "8",
                "notes": "Still a masterpiece.",
                "is_rewatch": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        entry = DiaryEntry.objects.get(user=self.user, item=self.item)
        self.assertEqual(float(entry.score), 8.0)
        self.assertTrue(entry.is_rewatch)
        self.assertEqual(entry.notes, "Still a masterpiece.")
        self.assertEqual(entry.logged_at.date().isoformat(), "2026-05-01")

    def test_log_score_is_clamped(self):
        """An out-of-range score is clamped to 0-10."""
        self.client.post(
            reverse("diary_log"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "score": "42",
            },
        )
        entry = DiaryEntry.objects.get(user=self.user, item=self.item)
        self.assertEqual(float(entry.score), 10.0)

    def test_log_blank_score_is_none(self):
        """A blank score stores None (no rating), not zero."""
        self.client.post(
            reverse("diary_log"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "score": "",
            },
        )
        entry = DiaryEntry.objects.get(user=self.user, item=self.item)
        self.assertIsNone(entry.score)

    def test_log_rejects_unsupported_media_type(self):
        """Episodes are not a diary media type."""
        response = self.client.post(
            reverse("diary_log"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.EPISODE.value,
                "media_id": "238",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(DiaryEntry.objects.count(), 0)

    def test_log_rejects_invalid_date(self):
        """A malformed date 400s instead of silently using today."""
        response = self.client.post(
            reverse("diary_log"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "logged_at": "not-a-date",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_htmx_log_returns_item_fragment(self):
        """An HTMX log returns the per-item diary card with the new entry."""
        response = self.client.post(
            reverse("diary_log"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "notes": "first watch",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "first watch")
        self.assertContains(response, 'id="item-diary"')

    def test_diary_page_lists_entries(self):
        """The diary page renders the user's entries grouped by day."""
        DiaryEntry.objects.create(user=self.user, item=self.item, notes="logged note")
        response = self.client.get(reverse("diary"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "logged note")
        self.assertContains(response, "The Godfather")

    def test_delete_removes_only_own_entry(self):
        """A user can't delete another user's diary entry."""
        other_credentials = {"username": "other", "password": "12345"}
        other = get_user_model().objects.create_user(**other_credentials)
        other_entry = DiaryEntry.objects.create(user=other, item=self.item)
        response = self.client.post(
            reverse("diary_delete", args=[other_entry.pk]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(DiaryEntry.objects.filter(pk=other_entry.pk).exists())

    def test_delete_own_entry(self):
        """A user can delete their own entry."""
        entry = DiaryEntry.objects.create(user=self.user, item=self.item)
        response = self.client.post(reverse("diary_delete", args=[entry.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DiaryEntry.objects.filter(pk=entry.pk).exists())


class RouletteViewTests(TestCase):
    """The "decide for me" backlog spinner."""

    def setUp(self):
        """Create a user and a planning movie."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Godfather",
            image="http://example.com/image.jpg",
        )

    def test_roulette_page_renders(self):
        """The roulette shell renders with controls."""
        response = self.client.get(reverse("roulette"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Decide for me")

    def test_spin_returns_planning_pick(self):
        """A spin surfaces a planning item."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        response = self.client.get(
            reverse("roulette_spin"),
            {"status": Status.PLANNING.value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Godfather")

    def test_spin_respects_media_type_filter(self):
        """Filtering to a type with no backlog returns the empty state."""
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        response = self.client.get(
            reverse("roulette_spin"),
            {"status": Status.PLANNING.value, "media_type": MediaTypes.BOOK.value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "The Godfather")

    def test_spin_empty_backlog(self):
        """No matching items yields the empty-state copy, not an error."""
        response = self.client.get(reverse("roulette_spin"))
        self.assertEqual(response.status_code, 200)


class DismissedItemsViewTests(TestCase):
    """Manage / restore Browse 'not interested' dismissals."""

    def setUp(self):
        """Create a user with a dismissed item and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.dismissed = DismissedItem.objects.create(
            user=self.user,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            media_id="238",
            title="The Godfather",
        )

    def test_page_lists_dismissed(self):
        """The dismissed page lists the user's dismissals."""
        response = self.client.get(reverse("dismissed_items"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Godfather")

    def test_undismiss_removes_row(self):
        """Restoring a dismissal deletes the row."""
        response = self.client.post(
            reverse("undismiss_item"),
            {
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            DismissedItem.objects.filter(pk=self.dismissed.pk).exists(),
        )
