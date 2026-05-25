import logging

from celery import states
from celery.signals import before_task_publish
from django.apps import apps
from django.core.cache import cache
from django.db.backends.signals import connection_created
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_celery_results.models import TaskResult

logger = logging.getLogger(__name__)


@receiver(connection_created)
def setup_sqlite_pragmas(sender, connection, **kwargs):  # noqa: ARG001
    """Set up SQLite pragmas for WAL mode and busy timeout on connection creation."""
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=wal;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()


def _invalidate_taste(user_id, media_type):
    """Drop the taste profile cache so the next read rebuilds.

    Imported lazily to avoid pulling the providers / cache stack at
    module-import time (this file runs early during Django startup).
    """
    from app import taste  # noqa: PLC0415

    taste.invalidate(user_id, media_type)


def _invalidate_sidebar_counts(user_id):
    """Drop the cached per-user sidebar count dict.

    The key shape matches ``SIDEBAR_COUNTS_CACHE_KEY`` in
    ``app.templatetags.app_tags``; duplicated as a literal here to avoid
    importing the templatetags module at signal-registration time.
    """
    cache.delete(f"app:sidebar_counts:user:{user_id}")


def _hook_taste_invalidation():
    """Wire post_save / post_delete on every Media subclass + DismissedItem.

    Connecting per-model lets us pass the right ``media_type`` straight
    through without inspecting the instance, and matches the
    media-type-specific cache keys ``taste.invalidate`` uses.
    """
    from app.models import DismissedItem, MediaTypes  # noqa: PLC0415

    for media_type in MediaTypes.values:
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        # Episode rows live under a Season and have no ``user_id`` of
        # their own — skip wiring; the parent Season's save fires its
        # own signal when an episode finale flips the season status.
        if not any(f.name == "user" for f in model._meta.fields):
            continue
        # Closure captures media_type via default arg to avoid the late-binding pitfall.

        def _on_save(sender, instance, media_type=media_type, **kwargs):  # noqa: ARG001
            _invalidate_taste(instance.user_id, media_type)
            _invalidate_sidebar_counts(instance.user_id)

        def _on_delete(sender, instance, media_type=media_type, **kwargs):  # noqa: ARG001
            _invalidate_taste(instance.user_id, media_type)
            _invalidate_sidebar_counts(instance.user_id)

        post_save.connect(_on_save, sender=model, weak=False)
        post_delete.connect(_on_delete, sender=model, weak=False)

    @receiver(post_save, sender=DismissedItem, weak=False)
    def on_dismiss(sender, instance, **kwargs):  # noqa: ARG001
        _invalidate_taste(instance.user_id, instance.media_type)

    @receiver(post_delete, sender=DismissedItem, weak=False)
    def on_undismiss(sender, instance, **kwargs):  # noqa: ARG001
        _invalidate_taste(instance.user_id, instance.media_type)


_hook_taste_invalidation()


@before_task_publish.connect
def create_task_result_on_publish(sender=None, headers=None, body=None, **kwargs):  # noqa: ARG001
    """Create a TaskResult object with PENDING status on task publish.

    https://github.com/celery/django-celery-results/issues/286#issuecomment-1279161047
    """
    if "task" not in headers:
        return

    TaskResult.objects.store_result(
        content_type="application/json",
        content_encoding="utf-8",
        task_id=headers["id"],
        result=None,
        status=states.PENDING,
        task_name=headers["task"],
        task_args=headers.get("argsrepr", ""),
        task_kwargs=headers.get("kwargsrepr", ""),
    )
