"""Celery tasks for the library app.

``auto_match_library_file`` runs the provider auto-match for a freshly
uploaded ``LibraryFile`` off the request path. Enqueued from the upload
view after the row is saved; runs inline in tests (CELERY eager).
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="Auto-match library file")
def auto_match_library_file(library_file_id):
    """Resolve one uploaded LibraryFile to a metadata provider work.

    Loads the row and delegates to
    ``library.matching.resolve_library_file_to_provider`` (which catches
    its own provider/API errors and never raises). A vanished row is a
    no-op — the upload may have been deleted before the task ran.
    """
    from library.matching import resolve_library_file_to_provider  # noqa: PLC0415
    from library.models import LibraryFile  # noqa: PLC0415

    library_file = LibraryFile.objects.filter(pk=library_file_id).first()
    if not library_file:
        logger.info(
            "Auto-match skipped: LibraryFile %s no longer exists.",
            library_file_id,
        )
        return

    resolve_library_file_to_provider(library_file)
