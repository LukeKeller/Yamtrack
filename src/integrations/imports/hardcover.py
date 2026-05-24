import logging
from datetime import UTC, datetime

from django.conf import settings
from django.utils.dateparse import parse_datetime

import app
from app.models import MediaTypes, Sources, Status
from integrations import hardcover_client
from integrations.hardcover_client import HardcoverAPIError, HardcoverAuthError
from integrations.imports import helpers
from integrations.imports.base import BaseImporter
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

PAGE_SIZE = 100

# Hardcover status_id -> Yamtrack Status
HARDCOVER_STATUS_MAP = {
    1: Status.PLANNING.value,  # Want to Read
    2: Status.IN_PROGRESS.value,  # Currently Reading
    3: Status.COMPLETED.value,  # Read
    4: Status.PAUSED.value,  # Paused
    5: Status.DROPPED.value,  # Did Not Finish
}


def _execute_import(query, variables, token):
    """Run a GraphQL query via the shared client, re-raising as MediaImportError.

    Wrapping here keeps the importer's UI surface (which renders
    MediaImportError messages as user-facing import failures) unchanged
    after the client extraction.
    """
    try:
        return hardcover_client.execute(query, variables, token)
    except (HardcoverAuthError, HardcoverAPIError) as error:
        raise MediaImportError(str(error)) from error


def get_username(token):
    """Validate the token and return the Hardcover username."""
    try:
        _hc_id, username = hardcover_client.get_me(token)
    except (HardcoverAuthError, HardcoverAPIError) as error:
        raise MediaImportError(str(error)) from error
    return username


def importer(token, user, mode, username=None):  # noqa: ARG001
    """Import a user's books from Hardcover.

    Args:
        token (str): Encrypted API token.
        user: Django user object to import data for.
        mode (str): "new" or "overwrite".
        username (str, optional): Hardcover username; unused (kept for shared
            import_media signature parity with other token-based importers).
    """
    return HardcoverImporter(token, user, mode).import_data()


class HardcoverImporter(BaseImporter):
    """Import a user's book library from Hardcover."""

    source_label = "Hardcover"

    USER_BOOKS_QUERY = """
    query ($limit: Int!, $offset: Int!) {
      me {
        user_books(
          order_by: {updated_at: desc},
          limit: $limit,
          offset: $offset
        ) {
          id
          book_id
          status_id
          rating
          review_raw
          updated_at
          book {
            id
            title
            pages
            cached_image(path: "url")
          }
          user_book_reads(
            order_by: {finished_at: desc_nulls_last, started_at: desc_nulls_last},
            limit: 1
          ) {
            progress_pages
            started_at
            finished_at
          }
        }
      }
    }
    """

    def __init__(self, token, user, mode):
        """Initialize the importer.

        Args:
            token (str): Encrypted API token (decrypted on init).
            user: Django user object.
            mode (str): "new" or "overwrite".
        """
        super().__init__(user, mode)
        self.token = helpers.decrypt(token)

    def import_data(self):
        """Stream the user's library and bulk-create books."""
        from integrations.signals import inbound_sync_window  # noqa: PLC0415

        for entry in self._iter_user_books():
            try:
                self._process_entry(entry)
            except Exception as e:
                msg = f"Error processing Hardcover entry: {entry}"
                raise MediaImportUnexpectedError(msg) from e

        # Wrap the bulk writes so the outbound post_save handler doesn't
        # treat them as user edits and echo them back to Hardcover.
        with inbound_sync_window():
            return self.finalize()

    def _iter_user_books(self):
        offset = 0
        while True:
            data = _execute_import(
                self.USER_BOOKS_QUERY,
                {"limit": PAGE_SIZE, "offset": offset},
                self.token,
            )
            me_list = data.get("me") or []
            if not me_list:
                return

            user_books = me_list[0].get("user_books") or []
            if not user_books:
                return

            logger.info(
                "Fetched %s Hardcover user_books (offset=%s)",
                len(user_books),
                offset,
            )
            yield from user_books

            if len(user_books) < PAGE_SIZE:
                return
            offset += PAGE_SIZE

    def _process_entry(self, entry):
        book_data = entry.get("book") or {}
        book_id = book_data.get("id") or entry.get("book_id")
        if not book_id:
            return

        book_id_str = str(book_id)
        title = book_data.get("title") or f"Hardcover #{book_id_str}"

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.BOOK.value,
            Sources.HARDCOVER.value,
            book_id_str,
            self.mode,
        ):
            return

        status_id = entry.get("status_id")
        status = HARDCOVER_STATUS_MAP.get(status_id)
        if not status:
            self.warnings.append(
                f"{title}: unknown Hardcover status_id {status_id}; skipped.",
            )
            return

        item, _ = app.models.Item.objects.get_or_create(
            media_id=book_id_str,
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            defaults={
                "title": title,
                "image": book_data.get("cached_image") or settings.IMG_NONE,
            },
        )

        rating = entry.get("rating")
        score = round(float(rating) * 2, 1) if rating is not None else None

        latest_read = (entry.get("user_book_reads") or [{}])[0]
        progress_pages = latest_read.get("progress_pages") or 0
        if status == Status.COMPLETED.value:
            # Completed books should show full progress when we know the page count
            progress_pages = book_data.get("pages") or progress_pages

        instance = app.models.Book(
            item=item,
            user=self.user,
            score=score,
            progress=progress_pages or 0,
            status=status,
            start_date=_parse_hc_date(latest_read.get("started_at")),
            end_date=_parse_hc_date(latest_read.get("finished_at")),
            notes=entry.get("review_raw") or "",
        )

        raw_updated = entry.get("updated_at")
        updated_at = parse_datetime(raw_updated) if raw_updated else None
        if updated_at:
            instance._history_date = updated_at

        self.bulk_media[MediaTypes.BOOK.value].append(instance)


def _parse_hc_date(raw):
    """Parse a Hardcover "YYYY-MM-DD" or ISO datetime string to an aware datetime."""
    if not raw:
        return None
    dt = parse_datetime(raw)
    if dt:
        return dt
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None
