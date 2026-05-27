# ruff: noqa: D102 — test methods are self-documenting via name
"""Tests for filename-mode auto-matching.

Covers the helper module (candidate generation, hash lookup) plus the
integration points: kosync PUT auto-binds when a filename match
exists, and the unmatched page surfaces per-row match suggestions.
"""

import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Book, Item, MediaTypes, Sources, Status
from integrations.koreader_filename import (
    candidate_filenames,
    candidate_hashes,
    find_match_for_hash,
    primary_expected_filename,
)
from integrations.models import KOReaderBookMapping


def _md5(value):
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _make_user(username="reader"):
    return get_user_model().objects.create_user(username=username, password="x")  # noqa: S106


def _make_book_item(*, title="The Test Book", media_id="OL123W"):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.OPENLIBRARY.value,
        media_type=MediaTypes.BOOK.value,
        title=title,
    )


class CandidateFilenameTests(TestCase):
    """``candidate_filenames`` generates plausible KOReader filenames."""

    def test_includes_title_with_known_extensions(self):
        item = _make_book_item(title="The Pragmatic Programmer")
        names = candidate_filenames(item)
        self.assertIn("The Pragmatic Programmer.epub", names)
        self.assertIn("The Pragmatic Programmer.pdf", names)
        self.assertIn("The Pragmatic Programmer.cbz", names)

    def test_lowercase_variant_emitted_when_title_has_uppercase(self):
        item = _make_book_item(title="Dune")
        names = candidate_filenames(item)
        self.assertIn("Dune.epub", names)
        self.assertIn("dune.epub", names)

    def test_no_lowercase_duplicate_when_title_is_all_lowercase(self):
        item = _make_book_item(title="nineteen eighty-four")
        names = candidate_filenames(item)
        # Only the original-case variant; no duplicate lowercase entry.
        self.assertEqual(names.count("nineteen eighty-four.epub"), 1)

    def test_empty_title_returns_empty_list(self):
        item = _make_book_item(title="")
        self.assertEqual(candidate_filenames(item), [])

    def test_primary_expected_filename_is_first_candidate(self):
        item = _make_book_item(title="Dune")
        self.assertEqual(primary_expected_filename(item), "Dune.epub")

    def test_primary_expected_filename_none_for_empty_title(self):
        item = _make_book_item(title="")
        self.assertIsNone(primary_expected_filename(item))


class CandidateHashTests(TestCase):
    """``candidate_hashes`` produces md5(filename) keys for each candidate."""

    def test_hash_matches_md5_of_filename(self):
        item = _make_book_item(title="Foundation")
        hashes = candidate_hashes(item)
        self.assertIn(_md5("Foundation.epub"), hashes)
        self.assertEqual(hashes[_md5("Foundation.epub")], "Foundation.epub")


class FindMatchTests(TestCase):
    """``find_match_for_hash`` scans a user's library for filename matches."""

    def setUp(self):
        self.user = _make_user()

    def test_returns_none_when_user_has_no_books(self):
        self.assertIsNone(find_match_for_hash(self.user, _md5("anything.epub")))

    def test_returns_none_when_hash_is_empty(self):
        self.assertIsNone(find_match_for_hash(self.user, ""))

    def test_matches_title_dot_epub(self):
        item = _make_book_item(title="Project Hail Mary")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        matched = find_match_for_hash(
            self.user,
            _md5("Project Hail Mary.epub"),
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched.pk, item.pk)

    def test_matches_lowercased_variant(self):
        item = _make_book_item(title="Dune")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        matched = find_match_for_hash(self.user, _md5("dune.epub"))
        self.assertEqual(matched.pk, item.pk)

    def test_matches_pdf_extension(self):
        item = _make_book_item(title="Some Manual")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        matched = find_match_for_hash(self.user, _md5("Some Manual.pdf"))
        self.assertEqual(matched.pk, item.pk)

    def test_does_not_match_other_users_books(self):
        item = _make_book_item(title="Other User Book")
        other = _make_user(username="other")
        Book.objects.create(
            user=other,
            item=item,
            status=Status.PLANNING.value,
        )
        self.assertIsNone(
            find_match_for_hash(self.user, _md5("Other User Book.epub")),
        )

    def test_no_match_for_arbitrary_hash(self):
        item = _make_book_item(title="Dune")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        self.assertIsNone(find_match_for_hash(self.user, "0" * 32))


class ProgressPutAutoBindTests(TestCase):
    """kosync PUT auto-binds the mapping when the filename hash matches."""

    def setUp(self):
        self.user = _make_user()
        self.item = _make_book_item(title="Dune")
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
        )

    def _put(self, document_hash, percentage=0.10):
        return self.client.put(
            reverse("koreader_progress_put"),
            data=json.dumps(
                {
                    "document": document_hash,
                    "percentage": percentage,
                    "device": "kindle",
                    "device_id": "k1",
                },
            ),
            content_type="application/json",
            HTTP_X_AUTH_USER=self.user.username,
            HTTP_X_AUTH_KEY=_md5(self.user.token),
        )

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_filename_hash_autobinds_to_matching_book(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        document = _md5("Dune.epub")
        response = self._put(document)
        self.assertEqual(response.status_code, 200)

        mapping = KOReaderBookMapping.objects.get(document_hash=document)
        self.assertEqual(mapping.item_id, self.item.pk)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_unmatched_hash_stays_unbound(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        document = _md5("Something Else.epub")
        response = self._put(document)
        self.assertEqual(response.status_code, 200)

        mapping = KOReaderBookMapping.objects.get(document_hash=document)
        self.assertIsNone(mapping.item_id)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_existing_unbound_mapping_gets_bound_on_next_put(self, mock_meta):
        # User had pre-existing unmatched mapping (e.g. created before
        # this feature shipped). Next sync should pick it up.
        mock_meta.return_value = {"max_progress": 400}
        document = _md5("Dune.epub")
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=document,
        )

        response = self._put(document, percentage=0.42)
        self.assertEqual(response.status_code, 200)

        mapping = KOReaderBookMapping.objects.get(document_hash=document)
        self.assertEqual(mapping.item_id, self.item.pk)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_manually_bound_mapping_is_not_overridden(self, mock_meta):
        # If a user manually linked a hash to one book, a later PUT
        # shouldn't re-route it to a different filename match.
        mock_meta.return_value = {"max_progress": 400}
        document = _md5("Dune.epub")
        other_item = _make_book_item(title="Other", media_id="OL999W")
        Book.objects.create(
            user=self.user,
            item=other_item,
            status=Status.PLANNING.value,
        )
        # User manually picked other_item earlier.
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=document,
            item=other_item,
        )

        response = self._put(document, percentage=0.5)
        self.assertEqual(response.status_code, 200)

        mapping = KOReaderBookMapping.objects.get(document_hash=document)
        # Manual bind stays — we didn't overwrite with filename guess.
        self.assertEqual(mapping.item_id, other_item.pk)


class UnmatchedPageFilenameSuggestionTests(TestCase):
    """``/koreader/unmatched`` surfaces per-row filename match suggestions."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)

    def test_per_row_match_when_filename_hash_recognised(self):
        item = _make_book_item(title="Dune")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        document = _md5("Dune.epub")
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=document,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        self.assertEqual(response.status_code, 200)
        rows = response.context["mapping_rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["filename_match_item"].pk, item.pk)

    def test_no_match_when_filename_hash_unknown(self):
        item = _make_book_item(title="Dune")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="f" * 32,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        rows = response.context["mapping_rows"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["filename_match_item"])

    @patch("app.providers.services.get_media_metadata")
    def test_expected_filename_hint_surfaced_for_likely_in_progress(
        self,
        mock_meta,
    ):
        # When there's no filename match but exactly one in-progress
        # book, the page surfaces both "Likely: <title>" and the rename
        # hint so the user can fix it on the device.
        mock_meta.return_value = {"max_progress": 400}
        item = _make_book_item(title="Foundation")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="d" * 32,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        self.assertEqual(response.context["likely_match_id"], item.pk)
        self.assertEqual(
            response.context["likely_expected_filename"],
            "Foundation.epub",
        )
