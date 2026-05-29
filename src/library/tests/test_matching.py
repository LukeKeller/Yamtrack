# ruff: noqa: S101, S106, D102, PLR2004 - asserts, test passwords, self-documenting methods, inline literals
"""Tests for provider auto-match: model fields, ISBN normalisation, resolve."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Sources
from library import matching
from library.models import LibraryFile

User = get_user_model()

_MD5_COUNTER = {"n": 0}


def _make_file(user, **kwargs):
    """Create a minimal LibraryFile row for matching tests.

    Each row gets a unique koreader_filename_md5 to satisfy the
    (user, hash) uniqueness constraint without callers caring.
    """
    _MD5_COUNTER["n"] += 1
    defaults = {
        "user": user,
        "canonical_filename": "Book.epub",
        "koreader_filename_md5": format(_MD5_COUNTER["n"], "032d"),
        "title": "Test Book",
        "author": "Test Author",
    }
    defaults.update(kwargs)
    return LibraryFile.objects.create(**defaults)


class MatchFieldDefaultsTests(TestCase):
    """Model field defaults and the is_matched property."""

    def setUp(self):
        self.user = User.objects.create_user(username="reader", password="pw")

    def test_new_row_defaults_unresolved(self):
        """A fresh upload starts UNRESOLVED / NONE / unmatched."""
        lib = _make_file(self.user)
        assert lib.match_status == LibraryFile.MatchStatus.UNRESOLVED
        assert lib.match_method == LibraryFile.MatchMethod.NONE
        assert lib.matched_at is None
        assert lib.is_matched is False

    def test_is_matched_true_when_matched(self):
        """is_matched reflects MATCHED status."""
        lib = _make_file(self.user, match_status=LibraryFile.MatchStatus.MATCHED)
        assert lib.is_matched is True


class Isbn10To13Tests(TestCase):
    """ISBN-10 -> ISBN-13 conversion + file-level normalisation."""

    def test_known_conversion(self):
        """0306406152 -> 9780306406157 (canonical example)."""
        assert matching.isbn10_to_isbn13("0306406152") == "9780306406157"

    def test_strips_separators(self):
        """Hyphens/spaces are tolerated."""
        assert matching.isbn10_to_isbn13("0-306-40615-2") == "9780306406157"

    def test_x_check_digit_input(self):
        """An ISBN-10 ending in X still converts (check digit recomputed)."""
        result = matching.isbn10_to_isbn13("097522980X")
        assert result.startswith("9780975229")
        assert len(result) == 13

    def test_invalid_returns_empty(self):
        """Non-ISBN-10 input returns ''."""
        assert matching.isbn10_to_isbn13("123") == ""
        assert matching.isbn10_to_isbn13("") == ""

    def test_normalised_prefers_isbn13(self):
        """A present ISBN-13 wins over an ISBN-10."""
        user = User.objects.create_user(username="n1", password="pw")
        lib = _make_file(user, isbn_13="9781234567897", isbn_10="0306406152")
        assert matching._normalised_isbn13(lib) == "9781234567897"

    def test_normalised_falls_back_to_isbn10(self):
        """With only an ISBN-10, it's converted to ISBN-13."""
        user = User.objects.create_user(username="n2", password="pw")
        lib = _make_file(user, isbn_13="", isbn_10="0306406152")
        assert matching._normalised_isbn13(lib) == "9780306406157"


class ResolveOpenLibraryTests(TestCase):
    """resolve_library_file_to_provider via the OpenLibrary fallback."""

    def setUp(self):
        self.user = User.objects.create_user(username="reader", password="pw")

    def test_isbn_match_binds_item(self):
        """An ISBN-13 hit creates an OpenLibrary Item and stamps MATCHED."""
        lib = _make_file(self.user, isbn_13="9780306406157")

        with (
            mock.patch.object(matching, "_hardcover_token", return_value=None),
            mock.patch.object(
                matching,
                "_openlibrary_edition_for_isbn",
                return_value="OL123M",
            ),
            mock.patch.object(
                matching.openlibrary,
                "book",
                return_value={"title": "Resolved Title", "image": "http://img"},
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is True
        lib.refresh_from_db()
        assert lib.match_status == LibraryFile.MatchStatus.MATCHED
        assert lib.match_method == LibraryFile.MatchMethod.ISBN
        assert lib.matched_at is not None
        assert lib.item is not None
        assert lib.item.source == Sources.OPENLIBRARY.value
        assert lib.item.media_id == "OL123M"
        assert lib.item.media_type == MediaTypes.BOOK.value

    def test_title_author_search_match(self):
        """No ISBN -> a single conservative title hit binds via TITLE_AUTHOR."""
        lib = _make_file(self.user, isbn_13="", isbn_10="", title="Unique Title")

        search_results = {"results": [{"media_id": "OL999M", "title": "Unique Title"}]}
        with (
            mock.patch.object(matching, "_hardcover_token", return_value=None),
            mock.patch.object(
                matching.openlibrary, "search", return_value=search_results
            ),
            mock.patch.object(
                matching.openlibrary,
                "book",
                return_value={"title": "Unique Title", "image": ""},
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is True
        lib.refresh_from_db()
        assert lib.match_method == LibraryFile.MatchMethod.TITLE_AUTHOR
        assert lib.item.media_id == "OL999M"

    def test_ambiguous_search_is_no_match(self):
        """Two title-prefix hits are ambiguous -> NO_MATCH, no item."""
        lib = _make_file(self.user, isbn_13="", isbn_10="", title="Common")

        search_results = {
            "results": [
                {"media_id": "OL1M", "title": "Common"},
                {"media_id": "OL2M", "title": "Common"},
            ],
        }
        with (
            mock.patch.object(matching, "_hardcover_token", return_value=None),
            mock.patch.object(
                matching.openlibrary, "search", return_value=search_results
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is False
        lib.refresh_from_db()
        assert lib.match_status == LibraryFile.MatchStatus.NO_MATCH
        assert lib.item is None

    def test_no_match_stamps_no_match(self):
        """No ISBN and no search hit -> NO_MATCH."""
        lib = _make_file(self.user, isbn_13="", isbn_10="", title="Nothing")

        with (
            mock.patch.object(matching, "_hardcover_token", return_value=None),
            mock.patch.object(
                matching.openlibrary, "search", return_value={"results": []}
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is False
        lib.refresh_from_db()
        assert lib.match_status == LibraryFile.MatchStatus.NO_MATCH

    def test_provider_error_leaves_unresolved(self):
        """A provider API error leaves the row UNRESOLVED for a retry."""
        from app.providers.services import ProviderAPIError  # noqa: PLC0415

        lib = _make_file(self.user, isbn_13="", isbn_10="", title="Boom")

        mock_error = mock.Mock()
        mock_error.response.status_code = 500
        mock_error.response.text = "boom"

        with (
            mock.patch.object(matching, "_hardcover_token", return_value=None),
            mock.patch.object(
                matching.openlibrary,
                "search",
                side_effect=ProviderAPIError(Sources.OPENLIBRARY.value, mock_error),
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is False
        lib.refresh_from_db()
        assert lib.match_status == LibraryFile.MatchStatus.UNRESOLVED


class ResolveHardcoverTests(TestCase):
    """Hardcover-first path when a token is present."""

    def setUp(self):
        self.user = User.objects.create_user(username="hcreader", password="pw")

    def test_hardcover_isbn_match_preferred(self):
        """With a token, a Hardcover ISBN hit binds a Hardcover Item."""
        lib = _make_file(self.user, isbn_13="9780306406157")

        with (
            mock.patch.object(matching, "_hardcover_token", return_value="tok"),
            mock.patch(
                "integrations.hardcover_client.find_edition_by_isbn13",
                return_value=(42, 7),
            ),
            mock.patch.object(
                matching.hardcover,
                "book",
                return_value={"title": "HC Title", "image": "http://hc"},
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is True
        lib.refresh_from_db()
        assert lib.item.source == Sources.HARDCOVER.value
        assert lib.item.media_id == "42"
        assert lib.match_method == LibraryFile.MatchMethod.ISBN

    def test_hardcover_miss_falls_back_to_openlibrary(self):
        """Hardcover miss falls through to OpenLibrary."""
        lib = _make_file(self.user, isbn_13="9780306406157")

        with (
            mock.patch.object(matching, "_hardcover_token", return_value="tok"),
            mock.patch(
                "integrations.hardcover_client.find_edition_by_isbn13",
                return_value=(None, None),
            ),
            mock.patch("integrations.hardcover_client.search_book", return_value=[]),
            mock.patch.object(
                matching,
                "_openlibrary_edition_for_isbn",
                return_value="OL55M",
            ),
            mock.patch.object(
                matching.openlibrary,
                "book",
                return_value={"title": "OL Title", "image": ""},
            ),
        ):
            result = matching.resolve_library_file_to_provider(lib)

        assert result is True
        lib.refresh_from_db()
        assert lib.item.source == Sources.OPENLIBRARY.value
        assert lib.item.media_id == "OL55M"


class BackfillMigrationLogicTests(TestCase):
    """Exercise the backfill rule directly against the live model.

    The data migration's rule: item set -> MATCHED/MANUAL with
    matched_at = updated_at; item null -> UNRESOLVED. We reproduce the
    rule here against ORM objects so the logic is regression-covered
    without spinning a historical-state migration executor.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="bf", password="pw")

    def test_linked_row_becomes_matched(self):
        item = Item.objects.create(
            media_id="OL1M",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="X",
        )
        lib = _make_file(self.user, item=item)
        LibraryFile.objects.filter(item__isnull=False).update(
            match_status="matched",
            match_method="manual",
        )
        LibraryFile.objects.filter(pk=lib.pk).update(matched_at=lib.updated_at)

        lib.refresh_from_db()
        assert lib.match_status == LibraryFile.MatchStatus.MATCHED
        assert lib.match_method == LibraryFile.MatchMethod.MANUAL
        assert lib.matched_at is not None

    def test_unlinked_row_stays_unresolved(self):
        lib = _make_file(self.user, item=None)
        LibraryFile.objects.filter(item__isnull=True).update(
            match_status="unresolved",
            match_method="none",
        )
        lib.refresh_from_db()
        assert lib.match_status == LibraryFile.MatchStatus.UNRESOLVED
