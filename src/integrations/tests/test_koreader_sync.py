# ruff: noqa: D102, S106 — test methods are self-documenting via
# name; "passwords" here are literal test fixtures.
"""KOReader (kosync) progress-sync endpoint tests.

External calls into ``providers.services.get_media_metadata`` are
patched per test so each test focuses on the kosync surface rather
than the upstream OpenLibrary lookup.
"""

import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Book, Item, MediaTypes, Sources, Status
from integrations.models import KOReaderBookMapping


def _md5(value):
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _make_user(username="reader"):
    return get_user_model().objects.create_user(username=username, password="x")


def _make_book_item(media_id="OL123W", source=Sources.OPENLIBRARY.value):
    return Item.objects.create(
        media_id=media_id,
        source=source,
        media_type=MediaTypes.BOOK.value,
        title="Test Book",
    )


def _auth_headers(user):
    return {
        "HTTP_X_AUTH_USER": user.username,
        "HTTP_X_AUTH_KEY": _md5(user.token),
    }


class AuthTests(TestCase):
    """Header-based auth covering both probe endpoints."""

    def setUp(self):
        self.user = _make_user()

    def test_users_auth_accepts_md5_of_token(self):
        response = self.client.get(
            reverse("koreader_users_auth"),
            **_auth_headers(self.user),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authorized": "OK"})

    def test_users_auth_rejects_bad_key(self):
        response = self.client.get(
            reverse("koreader_users_auth"),
            HTTP_X_AUTH_USER=self.user.username,
            HTTP_X_AUTH_KEY=_md5("not-the-token"),
        )
        self.assertEqual(response.status_code, 401)

    def test_users_auth_rejects_unknown_user(self):
        response = self.client.get(
            reverse("koreader_users_auth"),
            HTTP_X_AUTH_USER="ghost",
            HTTP_X_AUTH_KEY=_md5("anything"),
        )
        self.assertEqual(response.status_code, 401)

    def test_users_create_returns_username_on_valid_creds(self):
        response = self.client.post(
            reverse("koreader_users_create"),
            data=json.dumps(
                {"username": self.user.username, "password": _md5(self.user.token)},
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"username": self.user.username})

    def test_users_create_rejects_bad_password(self):
        response = self.client.post(
            reverse("koreader_users_create"),
            data=json.dumps({"username": self.user.username, "password": _md5("x")}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)


class ProgressPutTests(TestCase):
    """The PUT endpoint owns the write path; cover bound and unbound."""

    DOCUMENT = "a" * 32

    def setUp(self):
        self.user = _make_user()

    def _put(self, payload):
        return self.client.put(
            reverse("koreader_progress_put"),
            data=json.dumps(payload),
            content_type="application/json",
            **_auth_headers(self.user),
        )

    def test_unknown_document_creates_unbound_mapping(self):
        response = self._put(
            {
                "document": self.DOCUMENT,
                "progress": "/body/DocFragment[3]/body",
                "percentage": 0.25,
                "device": "kindle",
                "device_id": "abc",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["document"], self.DOCUMENT)
        self.assertIn("timestamp", body)

        mapping = KOReaderBookMapping.objects.get(
            user=self.user, document_hash=self.DOCUMENT
        )
        self.assertIsNone(mapping.item_id)
        self.assertEqual(mapping.last_percentage, 0.25)
        self.assertEqual(mapping.last_device, "kindle")

    def test_invalid_document_hash_rejected(self):
        response = self._put({"document": "not-hex", "percentage": 0.1})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(KOReaderBookMapping.objects.exists())

    def test_percentage_clamped_to_unit_interval(self):
        response = self._put({"document": self.DOCUMENT, "percentage": 2.5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            KOReaderBookMapping.objects.get().last_percentage,
            1.0,
        )

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_bound_mapping_updates_book_progress(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        item = _make_book_item()
        book = Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
            progress=0,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.DOCUMENT,
            item=item,
        )

        response = self._put(
            {"document": self.DOCUMENT, "percentage": 0.5, "progress": "x"},
        )
        self.assertEqual(response.status_code, 200)

        book.refresh_from_db()
        self.assertEqual(book.status, Status.IN_PROGRESS.value)
        self.assertEqual(book.progress, 200)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_full_percentage_completes_book(self, mock_meta):
        mock_meta.return_value = {"max_progress": 200}
        item = _make_book_item()
        book = Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=100,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.DOCUMENT,
            item=item,
        )

        self._put({"document": self.DOCUMENT, "percentage": 0.99})

        book.refresh_from_db()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.progress, 200)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_progress_never_goes_backwards_on_partial_reread(self, mock_meta):
        # User finished a book, then reopens it later — KOReader sends a
        # low percentage as they navigate. We shouldn't undo the page
        # count, only let progress move forward in the IN_PROGRESS case.
        mock_meta.return_value = {"max_progress": 400}
        item = _make_book_item()
        book = Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=300,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.DOCUMENT,
            item=item,
        )
        self._put({"document": self.DOCUMENT, "percentage": 0.1})

        book.refresh_from_db()
        self.assertEqual(book.progress, 300)


class ProgressGetTests(TestCase):
    """Snapshot fetch endpoint — returns whatever PUT last wrote."""

    DOCUMENT = "b" * 32

    def setUp(self):
        self.user = _make_user()

    def test_get_returns_404_when_unknown(self):
        response = self.client.get(
            reverse("koreader_progress_get", args=[self.DOCUMENT]),
            **_auth_headers(self.user),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"status": "not found"})

    def test_get_returns_stored_progress(self):
        # PUT first so the timestamp is server-set.
        self.client.put(
            reverse("koreader_progress_put"),
            data=json.dumps(
                {
                    "document": self.DOCUMENT,
                    "percentage": 0.4,
                    "progress": "/body",
                    "device": "kobo",
                    "device_id": "id1",
                },
            ),
            content_type="application/json",
            **_auth_headers(self.user),
        )
        response = self.client.get(
            reverse("koreader_progress_get", args=[self.DOCUMENT]),
            **_auth_headers(self.user),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["document"], self.DOCUMENT)
        self.assertEqual(body["percentage"], 0.4)
        self.assertEqual(body["device"], "kobo")
        self.assertIn("timestamp", body)


class LinkUnlinkTests(TestCase):
    """UI-side bind / unbind views for unlinked KOReader hashes."""

    DOCUMENT = "c" * 32

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)

    @patch("integrations.koreader.providers.services.get_media_metadata")
    def test_link_replays_last_percentage_onto_book(self, mock_meta):
        mock_meta.return_value = {"max_progress": 500}
        item = _make_book_item()
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
            progress=0,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.DOCUMENT,
            last_percentage=0.6,
            last_progress_at="2026-01-01T00:00:00Z",
        )

        response = self.client.post(
            reverse("koreader_link"),
            data={"document_hash": self.DOCUMENT, "item_id": item.pk},
        )
        self.assertEqual(response.status_code, 302)

        book = Book.objects.get(user=self.user, item=item)
        self.assertEqual(book.status, Status.IN_PROGRESS.value)
        self.assertEqual(book.progress, 300)

    def test_unlink_deletes_mapping(self):
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.DOCUMENT,
        )
        response = self.client.post(
            reverse("koreader_unlink"),
            data={"document_hash": self.DOCUMENT},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            KOReaderBookMapping.objects.filter(document_hash=self.DOCUMENT).exists()
        )
