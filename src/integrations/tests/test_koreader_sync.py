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
from integrations.models import KOReaderBookMapping, KOReaderProgressEvent


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

    def test_users_auth_accepts_lowercased_username(self):
        """KOReader's kosync plugin lowercases usernames before sending."""
        self.user.username = "Reader"
        self.user.save()
        response = self.client.get(
            reverse("koreader_users_auth"),
            HTTP_X_AUTH_USER="reader",
            HTTP_X_AUTH_KEY=_md5(self.user.token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authorized": "OK"})

    def test_users_auth_resolves_case_collision_by_token(self):
        """When two users differ only by case, the token md5 picks one."""
        self.user.username = "Reader"
        self.user.save()
        other = _make_user(username="reader")
        response = self.client.get(
            reverse("koreader_users_auth"),
            HTTP_X_AUTH_USER="reader",
            HTTP_X_AUTH_KEY=_md5(other.token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authorized": "OK"})


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


class ProgressEventLogTests(TestCase):
    """Event log writes — exercised on the kosync PUT hot path."""

    DOCUMENT = "b" * 32

    def setUp(self):
        self.user = _make_user()

    def _put(self, payload):
        return self.client.put(
            reverse("koreader_progress_put"),
            data=json.dumps(payload),
            content_type="application/json",
            **_auth_headers(self.user),
        )

    def test_each_put_appends_one_event(self):
        for pct in (0.1, 0.25, 0.5, 0.75):
            response = self._put(
                {
                    "document": self.DOCUMENT,
                    "percentage": pct,
                    "device": "kindle",
                    "device_id": "kindle-1",
                    "progress": f"page-{int(pct * 400)}",
                },
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(KOReaderProgressEvent.objects.count(), 4)
        events = list(
            KOReaderProgressEvent.objects.order_by("created_at").values(
                "percentage",
                "device",
                "device_id",
                "progress",
            ),
        )
        self.assertEqual([e["percentage"] for e in events], [0.1, 0.25, 0.5, 0.75])
        self.assertTrue(all(e["device"] == "kindle" for e in events))
        self.assertTrue(all(e["device_id"] == "kindle-1" for e in events))

    def test_event_preserves_device_per_push(self):
        """Mapping row only keeps the latest device; the event log keeps all."""
        self._put(
            {
                "document": self.DOCUMENT,
                "percentage": 0.1,
                "device": "kindle",
                "device_id": "k1",
            }
        )
        self._put(
            {
                "document": self.DOCUMENT,
                "percentage": 0.2,
                "device": "kobo",
                "device_id": "k2",
            }
        )

        devices_in_events = list(
            KOReaderProgressEvent.objects.order_by("created_at").values_list(
                "device_id",
                flat=True,
            ),
        )
        self.assertEqual(devices_in_events, ["k1", "k2"])
        # Mapping row reflects the latest only.
        mapping = KOReaderBookMapping.objects.get()
        self.assertEqual(mapping.last_device_id, "k2")


class BookHistoryViewTests(TestCase):
    """/koreader/history/<book_pk> renders the per-book timeline."""

    DOCUMENT = "c" * 32

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.item = _make_book_item()
        # PLANNING avoids the progress-save path that fetches metadata
        # from OpenLibrary — the view doesn't care about Book.status.
        self.book = Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
            progress=0,
        )
        self.mapping = KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash=self.DOCUMENT,
            item=self.item,
        )

    def _event(self, percentage, device="kindle", device_id="kindle-1"):
        return KOReaderProgressEvent.objects.create(
            mapping=self.mapping,
            user=self.user,
            percentage=percentage,
            device=device,
            device_id=device_id,
        )

    def test_renders_empty_state_with_no_events(self):
        response = self.client.get(
            reverse("koreader_book_history", args=[self.book.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No KOReader sync events yet")
        self.assertNotContains(response, "koreader-history-data")

    def test_renders_chart_with_events(self):
        for pct in (0.2, 0.45, 0.7):
            self._event(pct)
        response = self.client.get(
            reverse("koreader_book_history", args=[self.book.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "koreader-history-data")
        # The dataset payload is rendered inside a json_script tag, so the
        # label and the percentage values should both round-trip.
        self.assertContains(response, "kindle")
        self.assertIn("event_count", response.context)
        self.assertEqual(response.context["event_count"], 3)
        self.assertEqual(response.context["device_count"], 1)

    def test_groups_by_device(self):
        self._event(0.1, device="kindle", device_id="k1")
        self._event(0.2, device="kobo", device_id="k2")
        self._event(0.3, device="kindle", device_id="k1")
        response = self.client.get(
            reverse("koreader_book_history", args=[self.book.pk]),
        )
        self.assertEqual(response.context["device_count"], 2)
        self.assertEqual(response.context["event_count"], 3)

    def test_404_when_book_belongs_to_another_user(self):
        other = _make_user(username="other")
        other_book = Book.objects.create(
            user=other,
            item=self.item,
            status=Status.PLANNING.value,
        )
        response = self.client.get(
            reverse("koreader_book_history", args=[other_book.pk]),
        )
        self.assertEqual(response.status_code, 404)


class DevicesDashboardTests(TestCase):
    """/koreader/devices aggregates events across all books per user."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.item_a = _make_book_item(media_id="OLA")
        self.item_b = _make_book_item(media_id="OLB")
        self.map_a = KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="a" * 32,
            item=self.item_a,
        )
        self.map_b = KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="b" * 32,
            item=self.item_b,
        )

    def _event(self, mapping, device, device_id, percentage=0.1):
        return KOReaderProgressEvent.objects.create(
            mapping=mapping,
            user=self.user,
            percentage=percentage,
            device=device,
            device_id=device_id,
        )

    def test_renders_empty_state_with_no_events(self):
        response = self.client.get(reverse("koreader_devices"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No KOReader devices have synced yet")

    def test_aggregates_per_device(self):
        # kindle-1: 3 events across 2 books
        self._event(self.map_a, "kindle", "kindle-1")
        self._event(self.map_a, "kindle", "kindle-1", percentage=0.2)
        self._event(self.map_b, "kindle", "kindle-1")
        # kobo-2: 1 event, 1 book
        self._event(self.map_b, "kobo", "kobo-2")

        response = self.client.get(reverse("koreader_devices"))
        self.assertEqual(response.status_code, 200)
        devices = {
            (d["device"], d["device_id"]): d for d in response.context["devices"]
        }

        kindle = devices[("kindle", "kindle-1")]
        self.assertEqual(kindle["event_count"], 3)
        self.assertEqual(kindle["book_count"], 2)

        kobo = devices[("kobo", "kobo-2")]
        self.assertEqual(kobo["event_count"], 1)
        self.assertEqual(kobo["book_count"], 1)

    def test_other_user_events_are_excluded(self):
        other = _make_user(username="other")
        other_mapping = KOReaderBookMapping.objects.create(
            user=other,
            document_hash="d" * 32,
            item=self.item_a,
        )
        KOReaderProgressEvent.objects.create(
            mapping=other_mapping,
            user=other,
            percentage=0.5,
            device="someone-else",
            device_id="x",
        )

        response = self.client.get(reverse("koreader_devices"))
        device_ids = [d["device_id"] for d in response.context["devices"]]
        self.assertNotIn("x", device_ids)


class UnmatchedPageTests(TestCase):
    """/koreader/unmatched lists only unbound mappings + the linking form."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.item = _make_book_item()

    def test_lists_unbound_mappings_only(self):
        unbound = KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="e" * 32,
            last_percentage=0.25,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="f" * 32,
            item=self.item,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        self.assertEqual(response.status_code, 200)
        hashes = [m.document_hash for m in response.context["mappings"]]
        self.assertEqual(hashes, [unbound.document_hash])

    def test_other_user_unbound_excluded(self):
        other = _make_user(username="other")
        KOReaderBookMapping.objects.create(
            user=other,
            document_hash="d" * 32,
        )
        response = self.client.get(reverse("koreader_unmatched"))
        self.assertEqual(response.context["mappings"], [])

    def test_book_choices_scoped_to_user_books(self):
        Book.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
        )
        other = _make_user(username="other")
        other_item = _make_book_item(media_id="OL456W")
        Book.objects.create(
            user=other,
            item=other_item,
            status=Status.PLANNING.value,
        )
        response = self.client.get(reverse("koreader_unmatched"))
        choice_ids = [c["id"] for c in response.context["book_choices"]]
        self.assertIn(self.item.pk, choice_ids)
        self.assertNotIn(other_item.pk, choice_ids)

    @patch("app.providers.services.get_media_metadata")
    def test_in_progress_unbound_books_rank_first(self, mock_meta):
        """In-progress books without a KOReader mapping float to the top."""
        mock_meta.return_value = {"max_progress": 400}
        in_progress = _make_book_item(media_id="A")
        Book.objects.create(
            user=self.user,
            item=in_progress,
            status=Status.IN_PROGRESS.value,
        )
        planning = _make_book_item(media_id="B")
        Book.objects.create(
            user=self.user,
            item=planning,
            status=Status.PLANNING.value,
        )
        completed = _make_book_item(media_id="C")
        Book.objects.create(
            user=self.user,
            item=completed,
            status=Status.COMPLETED.value,
        )
        # Need an unbound mapping to make the page render.
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="e" * 32,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        ids = [c["id"] for c in response.context["book_choices"]]
        self.assertEqual(ids[0], in_progress.pk)

    @patch("app.providers.services.get_media_metadata")
    def test_already_bound_in_progress_is_de_ranked(self, mock_meta):
        """In-progress books already bound to a hash don't float to the top."""
        mock_meta.return_value = {"max_progress": 400}
        in_progress_bound = _make_book_item(media_id="A")
        Book.objects.create(
            user=self.user,
            item=in_progress_bound,
            status=Status.IN_PROGRESS.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="b" * 32,
            item=in_progress_bound,  # already bound to a different hash
        )

        in_progress_free = _make_book_item(media_id="B")
        Book.objects.create(
            user=self.user,
            item=in_progress_free,
            status=Status.IN_PROGRESS.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="e" * 32,  # unbound, triggers page render
        )

        response = self.client.get(reverse("koreader_unmatched"))
        ids = [c["id"] for c in response.context["book_choices"]]
        self.assertEqual(ids[0], in_progress_free.pk)

    @patch("app.providers.services.get_media_metadata")
    def test_likely_match_when_exactly_one_candidate(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        in_progress = _make_book_item(media_id="A")
        Book.objects.create(
            user=self.user,
            item=in_progress,
            status=Status.IN_PROGRESS.value,
        )
        # Adding a non-in-progress book doesn't disrupt the likely-match.
        other = _make_book_item(media_id="B")
        Book.objects.create(
            user=self.user,
            item=other,
            status=Status.PLANNING.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="e" * 32,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        self.assertEqual(response.context["likely_match_id"], in_progress.pk)
        self.assertEqual(response.context["likely_match_title"], in_progress.title)

    @patch("app.providers.services.get_media_metadata")
    def test_no_likely_match_when_multiple_in_progress(self, mock_meta):
        mock_meta.return_value = {"max_progress": 400}
        for media_id in ("A", "B"):
            item = _make_book_item(media_id=media_id)
            Book.objects.create(
                user=self.user,
                item=item,
                status=Status.IN_PROGRESS.value,
            )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="e" * 32,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        self.assertIsNone(response.context["likely_match_id"])

    def test_no_likely_match_when_zero_in_progress(self):
        item = _make_book_item(media_id="A")
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        KOReaderBookMapping.objects.create(
            user=self.user,
            document_hash="e" * 32,
        )

        response = self.client.get(reverse("koreader_unmatched"))
        self.assertIsNone(response.context["likely_match_id"])
