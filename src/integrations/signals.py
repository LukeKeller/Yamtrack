"""Signal-driven outbound push to Hardcover.

A ``post_save`` on ``Book`` enqueues the push task with a 10-second
countdown. The 10s window combined with Celery ``task_id`` dedup
collapses rapid edits (slider-drag, double-save) into one mutation.

Two layers of echo suppression keep this from looping with the inbound
importer:

1. A thread-local ``_inbound_sync_in_progress`` flag — the importer
   wraps its bulk writes in ``inbound_sync_window()`` so post_save
   handlers can no-op while inbound work is happening in this process.
2. A timestamp check — if ``Book.progressed_at`` is within 10s of
   ``Book.last_hardcover_sync_at``, the change almost certainly came
   from us pushing it just now, so skip.

Neither alone is enough: the flag misses cross-process echoes (importer
runs in worker, save fires in web); the timestamp misses simultaneous
local edits. Together they're conservative without being chatty.
"""

import logging
import threading
from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from app.models import Book
from integrations.models import HardcoverIntegration

logger = logging.getLogger(__name__)

_thread_state = threading.local()

ECHO_SUPPRESSION_WINDOW_SECONDS = 10
PUSH_DEBOUNCE_SECONDS = 10


class inbound_sync_window:  # noqa: N801 - context-manager naming convention
    """Mark the current thread as running an inbound Hardcover sync.

    Use as ``with inbound_sync_window(): ...`` around inbound bulk writes
    so the outbound post_save handler doesn't echo them back.
    """

    def __enter__(self):  # noqa: D105
        _thread_state.inbound = True

    def __exit__(self, exc_type, exc_val, exc_tb):  # noqa: D105
        _thread_state.inbound = False
        return False


def _inbound_sync_in_progress():
    return getattr(_thread_state, "inbound", False)


def _within_echo_window(book):
    last = book.last_hardcover_sync_at
    if not last:
        return False
    progressed = book.progressed_at or book.created_at
    if not progressed:
        return False
    return abs((progressed - last).total_seconds()) < ECHO_SUPPRESSION_WINDOW_SECONDS


@receiver(post_save, sender=Book, dispatch_uid="hardcover_push_book")
def push_book_on_save(sender, instance, created, update_fields=None, **kwargs):  # noqa: ARG001
    """Enqueue an outbound Hardcover push for a saved Book row."""
    if _inbound_sync_in_progress():
        return

    if _within_echo_window(instance):
        logger.debug("Skipping HC push for Book %s (within echo window).", instance.pk)
        return

    integration = HardcoverIntegration.objects.filter(
        user_id=instance.user_id,
        enabled=True,
    ).first()
    if not integration:
        return

    # Whether anything sync-worthy actually changed. The Book.tracker
    # (django-model-utils FieldTracker) gives us a reliable changed-fields
    # check that survives full saves vs partial saves.
    if not created:
        changed = set(instance.tracker.changed())
        watched = {"progress", "status", "score", "start_date", "end_date"}
        forced = update_fields and watched & set(update_fields)
        if not changed & watched and not forced:
            return

    # Import locally to avoid a circular dependency at app-startup time:
    # tasks.py imports many things; signals.py is imported from apps.ready.
    from integrations import tasks  # noqa: PLC0415

    task_id = f"hc_outbound_{integration.pk}_{instance.pk}"
    tasks.push_book_to_hardcover.apply_async(
        kwargs={"book_id": instance.pk, "integration_id": integration.pk},
        countdown=PUSH_DEBOUNCE_SECONDS,
        task_id=task_id,
    )
    logger.debug(
        "Queued Hardcover push for Book %s (task_id=%s, countdown=%ss).",
        instance.pk,
        task_id,
        PUSH_DEBOUNCE_SECONDS,
    )


def mark_pushed(book_id, when=None):
    """Stamp ``Book.last_hardcover_sync_at`` without firing post_save.

    Done via ``.update()`` so the bookkeeping write doesn't itself fire
    the signal we use to enqueue pushes (which would create an infinite
    loop and burn through the Hardcover rate cap in seconds).
    """
    Book.objects.filter(pk=book_id).update(
        last_hardcover_sync_at=when or timezone.now(),
    )


def push_eligible_window():
    """Return the cutoff for "recently pushed; safe to skip in reconcile."""
    return timezone.now() - timedelta(seconds=ECHO_SUPPRESSION_WINDOW_SECONDS)
