# ruff: noqa: D102 — test methods are self-documenting
"""Tests for the ``backfill_book_covers`` management command."""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from app.models import Item, MediaTypes, Sources


def _book_item(media_id, image):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.OPENLIBRARY.value,
        media_type=MediaTypes.BOOK.value,
        title=f"Book {media_id}",
        image=image,
    )


class BackfillBookCovers(TestCase):
    """The command fills covers for book items missing one."""

    @patch("app.providers.services.get_media_metadata")
    def test_backfills_placeholder_and_empty_images(self, mock_meta):
        placeholder = _book_item("OL1M", settings.IMG_NONE)
        empty = _book_item("OL2M", "")
        mock_meta.return_value = {
            "image": "https://covers.openlibrary.org/b/id/777-L.jpg",
        }

        out = StringIO()
        call_command("backfill_book_covers", stdout=out)

        placeholder.refresh_from_db()
        empty.refresh_from_db()
        self.assertEqual(
            placeholder.image,
            "https://covers.openlibrary.org/b/id/777-L.jpg",
        )
        self.assertEqual(empty.image, "https://covers.openlibrary.org/b/id/777-L.jpg")
        self.assertIn("updated=2", out.getvalue())

    @patch("app.providers.services.get_media_metadata")
    def test_leaves_existing_covers_untouched(self, mock_meta):
        good = _book_item("OL3M", "https://covers.openlibrary.org/b/id/1-L.jpg")
        call_command("backfill_book_covers", stdout=StringIO())
        good.refresh_from_db()
        # Item already has a cover, so it isn't in the queryset and the
        # provider is never consulted for it.
        self.assertEqual(good.image, "https://covers.openlibrary.org/b/id/1-L.jpg")
        mock_meta.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    def test_skips_when_provider_still_has_no_cover(self, mock_meta):
        item = _book_item("OL4M", settings.IMG_NONE)
        mock_meta.return_value = {"image": settings.IMG_NONE}
        out = StringIO()
        call_command("backfill_book_covers", stdout=out)
        item.refresh_from_db()
        self.assertEqual(item.image, settings.IMG_NONE)
        self.assertIn("skipped=1", out.getvalue())

    @patch("app.providers.services.get_media_metadata")
    def test_dry_run_writes_nothing(self, mock_meta):
        item = _book_item("OL5M", "")
        mock_meta.return_value = {
            "image": "https://covers.openlibrary.org/b/id/9-L.jpg",
        }
        call_command("backfill_book_covers", "--dry-run", stdout=StringIO())
        item.refresh_from_db()
        self.assertEqual(item.image, "")

    @patch("app.management.commands.backfill_book_covers.cache.delete")
    @patch("app.providers.services.get_media_metadata")
    def test_busts_provider_cache_before_fetching(self, mock_meta, mock_delete):
        _book_item("OL6M", settings.IMG_NONE)
        mock_meta.return_value = {"image": settings.IMG_NONE}
        call_command("backfill_book_covers", stdout=StringIO())
        # The stale 24h metadata cache is cleared so the resolver runs fresh.
        mock_delete.assert_called_once_with("openlibrary_book_OL6M")
