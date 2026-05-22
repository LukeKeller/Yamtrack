"""Cross-route smoke tests.

These tests don't validate any specific behaviour — they just request every
known route after seeding one tracked item per media type and assert the
server returns 200. The point is to catch regressions like a template that
iterates Status enum values incorrectly, a filter that raises on a media
type with no `unit` config, etc., before they reach a deploy.

Cheap to run (a few seconds) and stable: no external API calls, no Playwright,
no Redis (fakeredis via test_settings).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    TV,
    Anime,
    BoardGame,
    Book,
    Comic,
    Game,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Record,
    Sources,
    Status,
)


class SmokeTest(TestCase):
    """Request every route and check it doesn't 500."""

    @classmethod
    def setUpTestData(cls):
        """Create a user with one tracked item per media type."""
        cls.user = get_user_model().objects.create(
            username="smoke", theme="default", density="comfortable",
        )
        cls.user.set_password("smoke")
        cls.user.save()

        media_models = [
            (MediaTypes.MOVIE.value, Movie),
            (MediaTypes.TV.value, TV),
            (MediaTypes.ANIME.value, Anime),
            (MediaTypes.MANGA.value, Manga),
            (MediaTypes.GAME.value, Game),
            (MediaTypes.BOOK.value, Book),
            (MediaTypes.COMIC.value, Comic),
            (MediaTypes.BOARDGAME.value, BoardGame),
            (MediaTypes.RECORD.value, Record),
        ]
        cls.items = {}
        for media_type, model_cls in media_models:
            item = Item.objects.create(
                media_id=f"{media_type}1",
                source=Sources.MANUAL.value,
                media_type=media_type,
                title=f"Test {media_type}",
                image="/img.png",
            )
            cls.items[media_type] = item
            m = model_cls(user=cls.user, item=item, status=Status.IN_PROGRESS.value)
            m._history_user = cls.user
            m.save()

    def setUp(self):
        """Log in for each test."""
        self.client.login(username="smoke", password="smoke")  # noqa: S106

    def test_home_renders(self):
        """Home page renders cleanly with every media type tracked."""
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)

    def test_calendar_renders(self):
        """Calendar page renders 200."""
        self.assertEqual(self.client.get(reverse("calendar")).status_code, 200)

    def test_lists_renders(self):
        """Lists page renders 200."""
        self.assertEqual(self.client.get(reverse("lists")).status_code, 200)

    def test_statistics_renders(self):
        """Statistics page renders 200."""
        self.assertEqual(self.client.get(reverse("statistics")).status_code, 200)

    def test_each_media_list_renders(self):
        """Every per-type media list renders 200."""
        for media_type in MediaTypes.values:
            if media_type in {MediaTypes.EPISODE.value, MediaTypes.SEASON.value}:
                continue  # not in the sidebar; episode/season have other entry points
            url = reverse("medialist", kwargs={"media_type": media_type})
            with self.subTest(media_type=media_type):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_each_detail_page_renders(self):
        """Manual-source detail page renders 200 for every media type."""
        for media_type, item in self.items.items():
            url = reverse(
                "media_details",
                kwargs={
                    "source": Sources.MANUAL.value,
                    "media_type": media_type,
                    "media_id": item.media_id,
                    "title": "test",
                },
            )
            with self.subTest(media_type=media_type):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_settings_pages_render(self):
        """Each settings sub-page renders 200."""
        for name in (
            "account",
            "about",
            "advanced",
            "integrations",
            "notifications",
            "import_data",
            "export_data",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_onboarding_renders(self):
        """Onboarding wizard renders 200."""
        self.assertEqual(self.client.get(reverse("onboarding")).status_code, 200)
