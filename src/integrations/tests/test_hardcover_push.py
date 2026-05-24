# ruff: noqa: D102, S106, S107 — test methods are self-documenting via
# name; "passwords" here are literal test fixtures.
"""Outbound Hardcover push: tests for client, resolver, signals, views, task.

External GraphQL calls are mocked at ``hardcover_client.execute`` rather
than the underlying ``services.api_request`` so each test reads cleanly
and stays focused on what the push pipeline does with the data.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Book, Item, MediaTypes, Sources, Status
from integrations import hardcover_mapping, signals
from integrations.hardcover_client import HardcoverAuthError
from integrations.imports import helpers as import_helpers
from integrations.models import HardcoverBookMapping, HardcoverIntegration
from integrations.tasks import push_book_to_hardcover


def _make_user(username="bookworm"):
    return get_user_model().objects.create_user(username=username, password="x")


def _make_book_item(source=Sources.HARDCOVER.value, media_id="12345"):
    return Item.objects.create(
        media_id=media_id,
        source=source,
        media_type=MediaTypes.BOOK.value,
        title="Test Book",
    )


def _make_integration(user, token_plain="hctoken"):
    return HardcoverIntegration.objects.create(
        user=user,
        api_token=import_helpers.encrypt(token_plain),
        hardcover_user_id=99,
        hardcover_username="testuser",
        enabled=True,
    )


class ResolveBookIdTests(TestCase):
    """``hardcover_mapping.resolve_book_id`` dispatch + caching."""

    def setUp(self):
        self.user = _make_user()

    def test_hardcover_sourced_item_uses_media_id_directly(self):
        item = _make_book_item(source=Sources.HARDCOVER.value, media_id="55555")
        with patch("integrations.hardcover_client.execute") as mock_exec:
            book_id, edition_id, method = hardcover_mapping.resolve_book_id(
                item,
                token="t",
            )
        self.assertEqual(book_id, 55555)
        self.assertIsNone(edition_id)
        self.assertEqual(method, HardcoverBookMapping.MatchMethod.DIRECT_ID)
        # No API round-trip for the fast path.
        mock_exec.assert_not_called()
        # Direct-ID resolutions are not cached (Item.media_id IS the id).
        self.assertFalse(HardcoverBookMapping.objects.filter(item=item).exists())

    @patch("integrations.hardcover_mapping.openlibrary.book")
    @patch("integrations.hardcover_client.execute")
    def test_openlibrary_sourced_item_resolves_by_isbn13(
        self,
        mock_execute,
        mock_ol_book,
    ):
        item = _make_book_item(source=Sources.OPENLIBRARY.value, media_id="OL123W")
        mock_ol_book.return_value = {"details": {"isbn": ["9781234567890"]}}
        mock_execute.return_value = {
            "editions": [{"id": 222, "book": {"id": 111}}],
        }
        book_id, edition_id, method = hardcover_mapping.resolve_book_id(item, "t")
        self.assertEqual(book_id, 111)
        self.assertEqual(edition_id, 222)
        self.assertEqual(method, HardcoverBookMapping.MatchMethod.ISBN)
        # And it caches the result.
        self.assertTrue(
            HardcoverBookMapping.objects.filter(
                item=item, hardcover_book_id=111
            ).exists(),
        )

    @patch("integrations.hardcover_mapping.openlibrary.book")
    def test_cached_mapping_short_circuits(self, mock_ol_book):
        item = _make_book_item(source=Sources.OPENLIBRARY.value, media_id="OL999W")
        HardcoverBookMapping.objects.create(
            item=item,
            hardcover_book_id=42,
            hardcover_edition_id=7,
            match_method=HardcoverBookMapping.MatchMethod.MANUAL,
        )
        book_id, edition_id, method = hardcover_mapping.resolve_book_id(item, "t")
        self.assertEqual(
            (book_id, edition_id, method),
            (
                42,
                7,
                HardcoverBookMapping.MatchMethod.MANUAL,
            ),
        )
        # Skipped the network entirely thanks to the cache.
        mock_ol_book.assert_not_called()

    @patch("integrations.hardcover_mapping.openlibrary.book")
    @patch("integrations.hardcover_client.execute")
    def test_no_isbn_no_search_hits_raises_resolve_error(
        self,
        mock_execute,
        mock_ol_book,
    ):
        item = _make_book_item(source=Sources.OPENLIBRARY.value, media_id="OLZZZW")
        mock_ol_book.return_value = {"details": {}}
        mock_execute.return_value = {"search": {"results": {"hits": []}}}
        with self.assertRaises(hardcover_mapping.HardcoverResolveError):
            hardcover_mapping.resolve_book_id(item, "t")


class FieldMappingTests(TestCase):
    """Pure mapping helpers in ``hardcover_mapping``."""

    def test_status_round_trip(self):
        for value in (
            Status.PLANNING.value,
            Status.IN_PROGRESS.value,
            Status.COMPLETED.value,
            Status.PAUSED.value,
            Status.DROPPED.value,
        ):
            hc_id = hardcover_mapping.status_to_hardcover(value)
            self.assertEqual(hardcover_mapping.status_to_yamtrack(hc_id), value)

    def test_unknown_hc_status_is_none(self):
        self.assertIsNone(hardcover_mapping.status_to_yamtrack(999))

    def test_unknown_yamtrack_status_falls_back(self):
        # Falls back to "Currently Reading" so push jobs never crash.
        self.assertEqual(hardcover_mapping.status_to_hardcover("invented"), 2)

    def test_score_round_trip_at_half_steps(self):
        # 9.0 -> 4.5 -> 9.0 must be stable.
        self.assertEqual(hardcover_mapping.score_to_hardcover(9.0), 4.5)
        self.assertEqual(hardcover_mapping.score_to_yamtrack(4.5), 9.0)

    def test_score_none_passthrough(self):
        # "no rating" must stay "no rating" both directions.
        self.assertIsNone(hardcover_mapping.score_to_hardcover(None))
        self.assertIsNone(hardcover_mapping.score_to_yamtrack(None))

    def test_score_to_hardcover_rounds_to_half(self):
        self.assertEqual(hardcover_mapping.score_to_hardcover(7.3), 3.5)
        self.assertEqual(hardcover_mapping.score_to_hardcover(7.6), 4.0)

    def test_parse_hc_date_accepts_ymd_and_iso(self):
        self.assertIsNotNone(hardcover_mapping.parse_hc_date("2026-01-15"))
        self.assertIsNotNone(hardcover_mapping.parse_hc_date("2026-01-15T10:30:00Z"))
        self.assertIsNone(hardcover_mapping.parse_hc_date(""))
        self.assertIsNone(hardcover_mapping.parse_hc_date("not a date"))


class SignalEchoSuppressionTests(TestCase):
    """The post_save handler must not loop with the inbound importer."""

    def setUp(self):
        self.user = _make_user()
        self.integration = _make_integration(self.user)
        self.item = _make_book_item()
        # Book.save() reaches into the provider for max_progress; intercept it
        # so tests don't try to hit Hardcover for real.
        self._metadata_patch = patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": 300, "details": {"number_of_pages": 300}},
        )
        self._metadata_patch.start()
        self.addCleanup(self._metadata_patch.stop)

    def _save_book_with_progress(self, progress):
        book = Book(
            item=self.item,
            user=self.user,
            progress=progress,
            status=Status.IN_PROGRESS.value,
        )
        book.save()
        return book

    @patch("integrations.tasks.push_book_to_hardcover.apply_async")
    def test_progress_change_enqueues_task(self, mock_async):
        self._save_book_with_progress(50)
        self.assertEqual(mock_async.call_count, 1)
        kwargs = mock_async.call_args.kwargs
        self.assertIn("book_id", kwargs["kwargs"])
        self.assertIn("integration_id", kwargs["kwargs"])
        self.assertEqual(kwargs["countdown"], signals.PUSH_DEBOUNCE_SECONDS)

    @patch("integrations.tasks.push_book_to_hardcover.apply_async")
    def test_disabled_integration_skips_push(self, mock_async):
        self.integration.enabled = False
        self.integration.save()
        self._save_book_with_progress(50)
        mock_async.assert_not_called()

    @patch("integrations.tasks.push_book_to_hardcover.apply_async")
    def test_inbound_sync_window_blocks_push(self, mock_async):
        with signals.inbound_sync_window():
            self._save_book_with_progress(50)
        mock_async.assert_not_called()

    @patch("integrations.tasks.push_book_to_hardcover.apply_async")
    def test_within_echo_window_skips_push(self, mock_async):
        book = self._save_book_with_progress(50)
        mock_async.reset_mock()
        # Simulate "we just pushed this" — last_hardcover_sync_at very close
        # to progressed_at means the change came from us.
        Book.objects.filter(pk=book.pk).update(
            last_hardcover_sync_at=book.progressed_at,
        )
        book.refresh_from_db()
        book.progress = 75
        book.save()
        mock_async.assert_not_called()


class PushTaskTests(TestCase):
    """End-to-end task behavior with mocked GraphQL."""

    def setUp(self):
        self.user = _make_user()
        self.integration = _make_integration(self.user)
        self.item = _make_book_item()
        self._metadata_patch = patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": 300, "details": {"number_of_pages": 300}},
        )
        self._metadata_patch.start()
        self.addCleanup(self._metadata_patch.stop)
        # Suppress the outbound push signal during the seed write so it
        # doesn't fire a real (eager) Celery task in setUp.
        with signals.inbound_sync_window():
            self.book = Book.objects.create(
                item=self.item,
                user=self.user,
                progress=120,
                status=Status.IN_PROGRESS.value,
            )

    @patch("integrations.hardcover_client.insert_user_book_read")
    @patch("integrations.hardcover_client.get_user_book_for_book")
    @patch("integrations.hardcover_client.insert_user_book")
    def test_book_not_yet_on_hardcover_inserts_user_book_then_read(
        self,
        mock_insert_ub,
        mock_get_ub,
        mock_insert_read,
    ):
        mock_get_ub.return_value = None
        mock_insert_ub.return_value = 7777
        mock_insert_read.return_value = 1
        push_book_to_hardcover(self.book.pk, self.integration.pk)
        mock_insert_ub.assert_called_once_with(12345, 2, "hctoken")
        mock_insert_read.assert_called_once()
        sent_payload = mock_insert_read.call_args.args[1]
        self.assertEqual(sent_payload["progress_pages"], 120)

    @patch("integrations.hardcover_client.update_user_book_read")
    @patch("integrations.hardcover_client.get_user_book_for_book")
    def test_in_progress_book_with_active_read_updates_existing_read(
        self,
        mock_get_ub,
        mock_update_read,
    ):
        mock_get_ub.return_value = {
            "id": 9999,
            "status_id": 2,
            "rating": None,
            "user_book_reads": [
                {
                    "id": 555,
                    "progress_pages": 100,
                    "started_at": "2026-01-01",
                    "finished_at": None,
                    "edition_id": None,
                },
            ],
        }
        push_book_to_hardcover(self.book.pk, self.integration.pk)
        mock_update_read.assert_called_once()
        self.assertEqual(mock_update_read.call_args.args[0], 555)

    @patch("integrations.hardcover_client.insert_user_book_read")
    @patch("integrations.hardcover_client.update_user_book")
    @patch("integrations.hardcover_client.get_user_book_for_book")
    def test_completed_book_inserts_new_read_with_finished_at(
        self,
        mock_get_ub,
        mock_update_ub,
        mock_insert_read,
    ):
        self.book.status = Status.COMPLETED.value
        self.book.end_date = timezone.now()
        with signals.inbound_sync_window():
            self.book.save()
        mock_get_ub.return_value = {
            "id": 9999,
            "status_id": 2,
            "rating": None,
            "user_book_reads": [
                {
                    "id": 555,
                    "progress_pages": 100,
                    "started_at": "2026-01-01",
                    "finished_at": None,
                    "edition_id": None,
                },
            ],
        }
        mock_insert_read.return_value = 8
        push_book_to_hardcover(self.book.pk, self.integration.pk)
        # Completed → don't reuse the active read, append a new one.
        mock_insert_read.assert_called_once()
        payload = mock_insert_read.call_args.args[1]
        self.assertIn("finished_at", payload)
        # Status drifted from 2 → 3, so the user_book row gets updated too.
        mock_update_ub.assert_called_once()
        self.assertEqual(mock_update_ub.call_args.args[1], {"status_id": 3})

    @patch("integrations.hardcover_client.get_user_book_for_book")
    def test_auth_error_disables_integration(self, mock_get_ub):
        mock_get_ub.side_effect = HardcoverAuthError("Invalid token.")
        push_book_to_hardcover(self.book.pk, self.integration.pk)
        self.integration.refresh_from_db()
        self.assertFalse(self.integration.enabled)
        self.assertIn("Invalid token", self.integration.last_error)


class ConnectViewTests(TestCase):
    """The token-paste connect / disconnect views."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)

    @patch("integrations.views.hardcover_client.get_me")
    def test_connect_validates_token_and_creates_integration(self, mock_get_me):
        mock_get_me.return_value = (42, "alice")
        response = self.client.post(
            reverse("hardcover_connect"),
            data={"token": "raw_token_value"},
        )
        self.assertEqual(response.status_code, 302)
        integration = HardcoverIntegration.objects.get(user=self.user)
        self.assertEqual(integration.hardcover_user_id, 42)
        self.assertEqual(integration.hardcover_username, "alice")
        # Token is encrypted at rest; round-trip via decrypt should yield the raw value.
        self.assertEqual(
            import_helpers.decrypt(integration.api_token),
            "raw_token_value",
        )

    @patch("integrations.views.hardcover_client.get_me")
    def test_connect_with_invalid_token_does_not_create_row(self, mock_get_me):
        mock_get_me.side_effect = HardcoverAuthError("nope")
        self.client.post(reverse("hardcover_connect"), data={"token": "bad"})
        self.assertFalse(
            HardcoverIntegration.objects.filter(user=self.user).exists(),
        )

    def test_disconnect_deletes_integration(self):
        _make_integration(self.user)
        response = self.client.post(reverse("hardcover_disconnect"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            HardcoverIntegration.objects.filter(user=self.user).exists(),
        )
