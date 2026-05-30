from django.contrib.auth import get_user_model
from django.test import TestCase

from app import statistics as stats
from app.models import Book, Item, MediaTypes, Movie, Sources, Status


class BacklogStatsTests(TestCase):
    """app.statistics.get_backlog."""

    def setUp(self):
        """Create a user with a small planning backlog."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def _movie(self, media_id, status):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {media_id}",
            image="http://example.com/i.jpg",
        )
        return Movie.objects.create(item=item, user=self.user, status=status)

    def _book(self, media_id, status):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title=f"Book {media_id}",
            image="http://example.com/i.jpg",
        )
        return Book.objects.create(item=item, user=self.user, status=status)

    def test_counts_only_planning(self):
        """Backlog counts Planning items and ignores non-planning ones."""
        self._movie("1", Status.PLANNING.value)
        self._movie("2", Status.PLANNING.value)
        self._movie("3", Status.PAUSED.value)
        self._book("10", Status.PLANNING.value)

        backlog = stats.get_backlog(self.user)
        self.assertEqual(backlog["total_count"], 3)

        by_type = {row["media_type"]: row for row in backlog["rows"]}
        self.assertEqual(by_type[MediaTypes.MOVIE.value]["count"], 2)
        self.assertEqual(by_type[MediaTypes.BOOK.value]["count"], 1)
        self.assertNotIn(MediaTypes.GAME.value, by_type)

    def test_hours_estimate(self):
        """Estimated hours use the per-type average (movie = 2h)."""
        self._movie("1", Status.PLANNING.value)
        self._movie("2", Status.PLANNING.value)

        backlog = stats.get_backlog(self.user)
        self.assertTrue(backlog["has_estimate"])
        self.assertEqual(backlog["total_hours"], 4.0)

    def test_empty_backlog(self):
        """No planning items yields an empty, non-estimated summary."""
        backlog = stats.get_backlog(self.user)
        self.assertEqual(backlog["total_count"], 0)
        self.assertEqual(backlog["rows"], [])
        self.assertFalse(backlog["has_estimate"])

    def test_rows_sorted_by_count_desc(self):
        """Rows are ordered by descending count."""
        self._movie("1", Status.PLANNING.value)
        self._book("10", Status.PLANNING.value)
        self._book("11", Status.PLANNING.value)
        self._book("12", Status.PLANNING.value)

        backlog = stats.get_backlog(self.user)
        self.assertEqual(backlog["rows"][0]["media_type"], MediaTypes.BOOK.value)
        self.assertEqual(backlog["rows"][0]["count"], 3)
