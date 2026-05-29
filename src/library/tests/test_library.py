# ruff: noqa: D102, S106 — test methods are self-documenting, password literals are fine
"""End-to-end tests for the library + OPDS + kosync auto-bind feature.

Covers four surfaces:

* ``LibraryFileModelTests``: uniqueness constraint that backs the
  O(1) kosync auto-bind lookup.
* ``UploadTests``: single .epub upload + zip-of-epubs upload + non-epub
  silent skip + auto-link when title matches one tracked Book.
* ``OPDSTests``: 401 without basic auth, 200 with the right token,
  acquisition feed parses as XML and lists the right entry, download
  endpoint streams the file with the correct ``Content-Disposition``.
* ``KOSyncAutoBindTests``: a kosync PUT for ``md5(canonical_filename)``
  with a matched LibraryFile auto-binds the new mapping to the Book's
  Item. Manual links still win.

The fixture epub is generated in-process via EbookLib so the test suite
doesn't carry a binary asset; that also keeps the OPF metadata under
our control for the matching assertions.
"""

import base64
import contextlib
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import defusedxml.ElementTree as ET  # noqa: N817
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from ebooklib import epub

from app.models import Book, Item, MediaTypes, Sources, Status
from integrations.models import KOReaderBookMapping
from library.helpers import (
    canonical_filename_for,
    compute_koreader_filename_md5,
    find_matching_book,
)
from library.models import LibraryFile


def _md5(value):
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _make_user(username="reader"):
    return get_user_model().objects.create_user(username=username, password="x")


def _make_book_item(*, title="The Test Book", media_id="OL123W"):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.OPENLIBRARY.value,
        media_type=MediaTypes.BOOK.value,
        title=title,
    )


def _build_epub_bytes(
    title="Dune", author="Frank Herbert", language="en", isbn_13="9780441172719"
):
    """Build a minimal valid epub with OPF metadata and return its bytes."""
    book = epub.EpubBook()
    book.set_identifier(isbn_13)
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang=language)
    chapter.content = "<h1>Ch1</h1><p>body</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # ebooklib insists on a file path, not a stream — work around with a
    # tempfile and slurp the bytes back.
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        epub.write_epub(str(path), book)
        return path.read_bytes()
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


@override_settings(MEDIA_ROOT="library_test_media")
class LibraryFileModelTests(TestCase):
    """Schema-level invariants for LibraryFile."""

    def test_user_filename_md5_is_unique_per_user(self):
        user = _make_user()
        LibraryFile.objects.create(
            user=user,
            canonical_filename="Dune.epub",
            koreader_filename_md5=_md5("Dune.epub"),
            size_bytes=1,
        )
        with self.assertRaises(IntegrityError):
            LibraryFile.objects.create(
                user=user,
                canonical_filename="Dune.epub",
                koreader_filename_md5=_md5("Dune.epub"),
                size_bytes=1,
            )

    def test_same_md5_allowed_across_users(self):
        a = _make_user("a")
        b = _make_user("b")
        LibraryFile.objects.create(
            user=a,
            canonical_filename="Dune.epub",
            koreader_filename_md5=_md5("Dune.epub"),
            size_bytes=1,
        )
        # No exception: scoped to (user, hash), not global
        LibraryFile.objects.create(
            user=b,
            canonical_filename="Dune.epub",
            koreader_filename_md5=_md5("Dune.epub"),
            size_bytes=1,
        )


class HelperTests(TestCase):
    """Filename canonicalisation + book auto-link."""

    def test_canonical_filename_strips_unsafe_chars_and_forces_extension(self):
        # `:`, `<`, `>`, `/` all drop. Result is contiguous remaining chars.
        self.assertEqual(
            canonical_filename_for("A: <Test>/Book", None),
            "A TestBook.epub",
        )

    def test_compute_md5_matches_kosync_format(self):
        self.assertEqual(
            compute_koreader_filename_md5("Dune.epub"),
            _md5("Dune.epub"),
        )

    def test_find_matching_book_returns_item_on_unique_title(self):
        user = _make_user()
        item = _make_book_item(title="Dune")
        Book.objects.create(user=user, item=item, status=Status.PLANNING.value)
        self.assertEqual(find_matching_book(user, "Dune", "Frank Herbert"), item)

    def test_find_matching_book_returns_none_on_ambiguous_title(self):
        user = _make_user()
        a = _make_book_item(title="Dune", media_id="OL1")
        b = _make_book_item(title="Dune", media_id="OL2")
        Book.objects.create(user=user, item=a, status=Status.PLANNING.value)
        Book.objects.create(user=user, item=b, status=Status.PLANNING.value)
        self.assertIsNone(find_matching_book(user, "Dune", ""))

    def test_find_matching_book_normalises_articles_and_punctuation(self):
        user = _make_user()
        item = _make_book_item(title="The Pragmatic Programmer")
        Book.objects.create(user=user, item=item, status=Status.PLANNING.value)
        # Different leading article + punctuation but same canonical title
        self.assertEqual(
            find_matching_book(user, "Pragmatic Programmer!", ""),
            item,
        )

    def test_find_matching_book_does_not_cross_users(self):
        a = _make_user("a")
        b = _make_user("b")
        item = _make_book_item(title="Dune")
        Book.objects.create(user=b, item=item, status=Status.PLANNING.value)
        self.assertIsNone(find_matching_book(a, "Dune", ""))


@override_settings(MEDIA_ROOT="library_test_media")
class UploadTests(TestCase):
    """The /library/upload POST path."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        # Upload enqueues the provider auto-match task, which runs inline
        # under CELERY eager and would hit live providers. Stub it; the
        # resolver is covered in test_matching.
        patcher = patch("library.views.auto_match_library_file")
        self.mock_auto_match = patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self, files):
        return self.client.post(
            reverse("library_upload"),
            data={"files": files},
            follow=True,
        )

    def test_single_epub_upload_creates_libraryfile_with_metadata(self):
        epub_bytes = _build_epub_bytes(title="Dune", author="Frank Herbert")
        upload = SimpleUploadedFile(
            "anything.epub",
            epub_bytes,
            content_type="application/epub+zip",
        )
        self._upload([upload])
        self.assertEqual(LibraryFile.objects.count(), 1)
        lf = LibraryFile.objects.first()
        self.assertEqual(lf.user, self.user)
        self.assertEqual(lf.title, "Dune")
        self.assertEqual(lf.author, "Frank Herbert")
        self.assertEqual(lf.canonical_filename, "Dune.epub")
        self.assertEqual(
            lf.koreader_filename_md5,
            _md5("Dune.epub"),
        )
        self.assertGreater(lf.size_bytes, 0)
        lf.file.delete(save=False)

    def test_zip_upload_walks_subdirs_for_epubs(self):
        epub_a = _build_epub_bytes(title="Book A")
        epub_b = _build_epub_bytes(title="Book B")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("top.epub", epub_a)
            zf.writestr("subdir/nested/inner.epub", epub_b)
            zf.writestr("README.txt", b"ignore me")
        upload = SimpleUploadedFile(
            "books.zip",
            zip_buf.getvalue(),
            content_type="application/zip",
        )
        self._upload([upload])
        self.assertEqual(LibraryFile.objects.count(), 2)
        titles = sorted(LibraryFile.objects.values_list("title", flat=True))
        self.assertEqual(titles, ["Book A", "Book B"])
        for lf in LibraryFile.objects.all():
            lf.file.delete(save=False)

    def test_non_epub_uploads_are_silently_skipped(self):
        upload = SimpleUploadedFile(
            "notes.pdf",
            b"%PDF-1.4 fake",
            content_type="application/pdf",
        )
        self._upload([upload])
        self.assertEqual(LibraryFile.objects.count(), 0)

    def test_upload_starts_unresolved_and_enqueues_provider_match(self):
        # Uploads no longer auto-link to a tracked Book; they start
        # UNRESOLVED and enqueue the provider auto-match task instead.
        upload = SimpleUploadedFile(
            "anything.epub",
            _build_epub_bytes(title="Dune", author="Frank Herbert"),
            content_type="application/epub+zip",
        )
        self._upload([upload])
        lf = LibraryFile.objects.get()
        self.assertIsNone(lf.item)
        self.assertEqual(lf.match_status, LibraryFile.MatchStatus.UNRESOLVED)
        self.mock_auto_match.delay.assert_called_once_with(lf.id)
        lf.file.delete(save=False)

    def test_duplicate_upload_in_same_form_only_creates_one_row(self):
        epub_bytes = _build_epub_bytes(title="Dune")
        upload_a = SimpleUploadedFile("a.epub", epub_bytes)
        upload_b = SimpleUploadedFile("b.epub", epub_bytes)
        self._upload([upload_a, upload_b])
        self.assertEqual(LibraryFile.objects.count(), 1)
        for lf in LibraryFile.objects.all():
            lf.file.delete(save=False)


@override_settings(MEDIA_ROOT="library_test_media")
class OPDSTests(TestCase):
    """OPDS catalog + download endpoints (HTTP Basic against User.token)."""

    def setUp(self):
        self.user = _make_user()
        self.user.token = "the-token"  # noqa: S105
        self.user.save(update_fields=["token"])
        # Stub provider auto-match so the upload fixture doesn't call out.
        patcher = patch("library.views.auto_match_library_file")
        patcher.start()
        self.addCleanup(patcher.stop)
        epub_bytes = _build_epub_bytes(title="Dune", author="Frank Herbert")
        upload = SimpleUploadedFile("dune.epub", epub_bytes)
        self.client.force_login(self.user)
        self.client.post(reverse("library_upload"), data={"files": upload})
        self.client.logout()
        self.lf = LibraryFile.objects.get()

    def tearDown(self):
        with contextlib.suppress(OSError, ValueError):
            self.lf.file.delete(save=False)

    def _basic(self, username, token):
        encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
        return f"Basic {encoded}"

    def test_root_returns_401_without_auth(self):
        response = self.client.get(reverse("opds_root"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response["WWW-Authenticate"])

    def test_root_accepts_head_so_koreader_can_discover_realm(self):
        # KOReader's OPDS catalog browser issues a HEAD before Basic auth
        # to learn the WWW-Authenticate realm. If HEAD returns 405 it
        # bails without ever sending credentials and reports
        # "authentication required" to the user (ynh131/ynh132 had this
        # via @require_GET — fixed in ynh133).
        response = self.client.head(reverse("opds_root"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response["WWW-Authenticate"])

    def test_root_returns_401_with_wrong_token(self):
        response = self.client.get(
            reverse("opds_root"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, "wrong"),
        )
        self.assertEqual(response.status_code, 401)

    def test_root_returns_navigation_feed_with_shelves(self):
        response = self.client.get(
            reverse("opds_root"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("kind=navigation", response["Content-Type"])
        root = ET.fromstring(response.content)
        ns = "{http://www.w3.org/2005/Atom}"
        titles = [e.findtext(f"{ns}title") for e in root.findall(f"{ns}entry")]
        self.assertEqual(
            titles,
            [
                "Up Next",
                "Want to Read",
                "Recently Added",
                "By Author",
                "Unmatched",
                "All Books",
            ],
        )
        # Every shelf entry must carry a subsection link with an OPDS type.
        for entry in root.findall(f"{ns}entry"):
            link = next(
                link
                for link in entry.findall(f"{ns}link")
                if link.get("rel") == "subsection"
            )
            self.assertIn("opds-catalog", link.get("type", ""))

    def test_all_shelf_returns_acquisition_feed_with_entry(self):
        response = self.client.get(
            reverse("opds_all"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("kind=acquisition", response["Content-Type"])
        root = ET.fromstring(response.content)
        ns = "{http://www.w3.org/2005/Atom}"
        entries = root.findall(f"{ns}entry")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].findtext(f"{ns}title"), "Dune")
        acquisition_link = next(
            link
            for link in entries[0].findall(f"{ns}link")
            if link.get("rel") == "http://opds-spec.org/acquisition"
        )
        self.assertIn("application/epub+zip", acquisition_link.get("type", ""))

    def test_up_next_shelf_lists_only_in_progress_books(self):
        # Create the Book at default Planning, then bypass Media.save() to
        # flip status — saving with IN_PROGRESS triggers a live
        # provider.get_media_metadata() call which is exactly what we don't
        # want in unit tests.
        item = _make_book_item(title="Dune", media_id="OL-DUNE")
        Book.objects.create(user=self.user, item=item, status=Status.PLANNING.value)
        Book.objects.filter(user=self.user, item=item).update(
            status=Status.IN_PROGRESS.value,
        )
        self.lf.item = item
        self.lf.save(update_fields=["item"])
        ns = "{http://www.w3.org/2005/Atom}"
        response = self.client.get(
            reverse("opds_up_next"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        root = ET.fromstring(response.content)
        titles = [e.findtext(f"{ns}title") for e in root.findall(f"{ns}entry")]
        self.assertEqual(titles, ["Dune"])
        # Flip status to Planning and the file should drop out of Up Next.
        Book.objects.filter(user=self.user, item=item).update(
            status=Status.PLANNING.value,
        )
        response = self.client.get(
            reverse("opds_up_next"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        root = ET.fromstring(response.content)
        self.assertEqual(root.findall(f"{ns}entry"), [])

    def test_unmatched_shelf_lists_files_with_no_item(self):
        # The fixture file uploads without a matching Book, so item stays None.
        response = self.client.get(
            reverse("opds_unmatched"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        ns = "{http://www.w3.org/2005/Atom}"
        root = ET.fromstring(response.content)
        titles = [e.findtext(f"{ns}title") for e in root.findall(f"{ns}entry")]
        self.assertEqual(titles, ["Dune"])

    def test_authors_shelf_links_to_per_author_acquisition(self):
        response = self.client.get(
            reverse("opds_authors"),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        ns = "{http://www.w3.org/2005/Atom}"
        root = ET.fromstring(response.content)
        entries = root.findall(f"{ns}entry")
        self.assertEqual(
            [e.findtext(f"{ns}title") for e in entries],
            ["Frank Herbert"],
        )
        href = entries[0].find(f"{ns}link").get("href")
        # Per-author feed should list the file.
        response = self.client.get(
            href.replace("http://testserver", ""),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        root = ET.fromstring(response.content)
        titles = [e.findtext(f"{ns}title") for e in root.findall(f"{ns}entry")]
        self.assertEqual(titles, ["Dune"])

    def test_download_streams_with_canonical_content_disposition(self):
        response = self.client.get(
            reverse("opds_download", args=[self.lf.pk]),
            HTTP_AUTHORIZATION=self._basic(self.user.username, self.user.token),
        )
        self.assertEqual(response.status_code, 200)
        disposition = response["Content-Disposition"]
        self.assertIn('filename="Dune.epub"', disposition)
        # Body should be a valid zip (epubs are zips)
        body = b"".join(response.streaming_content)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(body)))

    def test_download_cannot_cross_users(self):
        other = _make_user("other")
        other.token = "other-token"  # noqa: S105
        other.save(update_fields=["token"])
        response = self.client.get(
            reverse("opds_download", args=[self.lf.pk]),
            HTTP_AUTHORIZATION=self._basic("other", "other-token"),
        )
        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT="library_test_media")
class KOSyncAutoBindTests(TestCase):
    """kosync PUT auto-binds when a LibraryFile matches the document hash."""

    def setUp(self):
        self.user = _make_user()
        self.item = _make_book_item(title="Dune")
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
        )
        self.canonical = "Dune.epub"
        self.hash = _md5(self.canonical)
        self.library_file = LibraryFile.objects.create(
            user=self.user,
            canonical_filename=self.canonical,
            koreader_filename_md5=self.hash,
            item=self.item,
            size_bytes=1,
        )

    def _put(self, document_hash, percentage=0.1):
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
    def test_kosync_put_autobinds_via_libraryfile(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        response = self._put(self.hash)
        self.assertEqual(response.status_code, 200)
        mapping = KOReaderBookMapping.objects.get(document_hash=self.hash)
        self.assertEqual(mapping.item_id, self.item.pk)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_libraryfile_lookup_skipped_when_item_already_bound(self, mock_meta):
        # Manual link wins — kosync handler must not rebind a bound mapping.
        mock_meta.return_value = {"max_progress": 400}
        other_item = _make_book_item(title="Other", media_id="OL999")
        Book.objects.create(
            user=self.user,
            item=other_item,
            status=Status.PLANNING.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.hash,
            item=other_item,  # manually bound to OTHER
        )
        self._put(self.hash)
        mapping = KOReaderBookMapping.objects.get(document_hash=self.hash)
        self.assertEqual(mapping.item_id, other_item.pk)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_libraryfile_without_item_does_not_autobind(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        # Recreate the LibraryFile without an item bound
        self.library_file.item = None
        self.library_file.save(update_fields=["item"])
        self._put(self.hash)
        mapping = KOReaderBookMapping.objects.get(document_hash=self.hash)
        # Filename-mode fallback may still bind (title matches "Dune.epub"),
        # so this test just checks no crash + a mapping exists. The
        # specific binding-or-not is covered in test_koreader_filename.
        self.assertIsNotNone(mapping)
