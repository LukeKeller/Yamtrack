import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

import events
from app.mixins import disable_fetch_releases
from app.models import MediaTypes
from app.templatetags import app_tags
from integrations import musicbrainz
from integrations.imports import (
    anilist,
    discogs,
    goodreads,
    hardcover,
    helpers,
    hltb,
    imdb,
    kitsu,
    mal,
    scrobbles,
    simkl,
    steam,
    trakt,
    yamtrack,
)

logger = logging.getLogger(__name__)
ERROR_TITLE = "\n\n\n Couldn't import the following media: \n\n"


def format_media_type_display(count, media_type):
    """Format media type display with proper pluralization."""
    if count == 0:
        return None
    if count == 1:
        return f"{count} {dict(MediaTypes.choices).get(media_type, media_type)}"
    return f"{count} {app_tags.media_type_readable_plural(media_type)}"


def format_import_message(imported_counts, warning_messages=None):
    """Format the import result message based on counts and warnings."""
    parts = [
        format_media_type_display(count, media_type)
        for media_type, count in imported_counts.items()
    ]
    parts = [p for p in parts if p is not None]

    if not parts:
        info_message = "No media was imported."
    else:
        info_message = f"Imported {helpers.join_with_commas_and(parts)}."

    if warning_messages:
        return f"{info_message} {ERROR_TITLE} {warning_messages}"
    return info_message


def import_media(
    importer_func,
    identifier,
    user_id,
    mode,
    oauth_username=None,
    **kwargs,
):
    """Handle the import process for different media services."""
    user = get_user_model().objects.get(id=user_id)

    with disable_fetch_releases():
        if oauth_username is None:
            imported_counts, warnings = importer_func(
                identifier,
                user,
                mode,
                **kwargs,
            )
        else:
            imported_counts, warnings = importer_func(
                identifier,
                user,
                mode,
                username=oauth_username,
                **kwargs,
            )

    events.tasks.reload_calendar.delay()

    return format_import_message(imported_counts, warnings)


@shared_task(name="Import from Trakt")
def import_trakt(user_id, mode, token=None, username=None, redirect_uri=None):
    """Celery task for importing media data from Trakt.

    Can import using either OAuth (token provided) or public username.
    """
    return import_media(
        trakt.importer,
        token,
        user_id,
        mode,
        username,
        redirect_uri=redirect_uri,
    )


@shared_task(name="Import from SIMKL")
def import_simkl(token, user_id, mode, username=None):  # noqa: ARG001
    """Celery task for importing media data from SIMKL."""
    return import_media(simkl.importer, token, user_id, mode)


@shared_task(name="Import from MyAnimeList")
def import_mal(username, user_id, mode):
    """Celery task for importing anime and manga data from MyAnimeList."""
    return import_media(mal.importer, username, user_id, mode)


@shared_task(name="Import from AniList")
def import_anilist(user_id, mode, token=None, username=None):
    """Celery task for importing media data from AniList."""
    return import_media(anilist.importer, token, user_id, mode, username)


@shared_task(name="Import from Kitsu")
def import_kitsu(username, user_id, mode):
    """Celery task for importing anime and manga data from Kitsu."""
    return import_media(kitsu.importer, username, user_id, mode)


@shared_task(name="Import from Yamtrack")
def import_yamtrack(file, user_id, mode):
    """Celery task for importing media data from Yamtrack."""
    return import_media(yamtrack.importer, file, user_id, mode)


@shared_task(name="Import from HowLongToBeat")
def import_hltb(file, user_id, mode):
    """Celery task for importing media data from HowLongToBeat."""
    return import_media(hltb.importer, file, user_id, mode)


@shared_task(name="Import from Steam")
def import_steam(username, user_id, mode):
    """Celery task for importing game data from Steam."""
    return import_media(steam.importer, username, user_id, mode)


@shared_task(name="Import from IMDB")
def import_imdb(file, user_id, mode):
    """Celery task for importing media data from IMDB."""
    return import_media(imdb.importer, file, user_id, mode)


@shared_task(name="Import from GoodReads")
def import_goodreads(file, user_id, mode):
    """Celery task for importing media data from GoodReads."""
    return import_media(goodreads.importer, file, user_id, mode)


@shared_task(name="Import from Hardcover")
def import_hardcover(user_id, mode, token, username=None):
    """Celery task for importing books from Hardcover."""
    return import_media(hardcover.importer, token, user_id, mode, username)


@shared_task(name="Import from Discogs")
def import_discogs(user_id, mode, token, username=None):
    """Celery task for importing vinyl records from Discogs."""
    return import_media(discogs.importer, token, user_id, mode, username)


@shared_task(name="Import scrobbles")
def import_scrobbles(file, user_id, mode):
    """Celery task for one-time scrobble import from a generic CSV."""
    return import_media(scrobbles.importer, file, user_id, mode)


@shared_task(name="Enrich scrobbles with MusicBrainz IDs")
def enrich_scrobble_mbids(limit=500):
    """Resolve MusicBrainz IDs for pending ListenBrainz scrobbles."""
    return musicbrainz.enrich_pending(limit=limit)


@shared_task(
    name="Push book to Hardcover",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=3,
    retry_jitter=True,
)
def push_book_to_hardcover(book_id, integration_id):
    """Push a single Book row's progress/status/score/dates to Hardcover.

    Resolves the Yamtrack Item to a Hardcover book id (using the cached
    mapping or fresh ISBN/title lookup), ensures a ``user_book`` exists
    for the user on Hardcover, then updates the latest reading session's
    ``progress_pages`` (or inserts a new session if there's no active
    one). Stamps ``Book.last_hardcover_sync_at`` so the inbound importer
    doesn't echo the change back.

    Retries on any exception with exponential backoff: 60s, 2min, 8min.
    Auth errors are caught higher up and disable the integration instead.
    """
    from app.models import Book  # noqa: PLC0415
    from integrations import hardcover_mapping  # noqa: PLC0415
    from integrations.hardcover_client import HardcoverAuthError  # noqa: PLC0415
    from integrations.imports import helpers as import_helpers  # noqa: PLC0415
    from integrations.models import HardcoverIntegration  # noqa: PLC0415

    integration = HardcoverIntegration.objects.filter(
        pk=integration_id,
        enabled=True,
    ).first()
    if not integration:
        logger.info(
            "HC push skipped: integration %s missing or disabled.", integration_id
        )
        return

    book = Book.objects.filter(pk=book_id).select_related("item").first()
    if not book:
        logger.info("HC push skipped: Book %s no longer exists.", book_id)
        return

    token = import_helpers.decrypt(integration.api_token)

    try:
        _push_book_inner(book, token, integration_id)
    except hardcover_mapping.HardcoverResolveError as error:
        # No match — record on the integration row so the UI can surface it,
        # but don't keep retrying (each retry costs API budget).
        HardcoverIntegration.objects.filter(pk=integration_id).update(
            last_error=str(error),
            last_error_at=timezone.now(),
        )
        logger.warning("HC push: %s", error)
    except HardcoverAuthError as error:
        # Token's been rotated / revoked. Disable the integration so we
        # stop hitting the API; the user reconnects from the settings UI.
        HardcoverIntegration.objects.filter(pk=integration_id).update(
            enabled=False,
            last_error=str(error),
            last_error_at=timezone.now(),
        )
        logger.warning("HC push disabled (auth error): %s", error)


def _push_book_inner(book, token, integration_id):
    """Run the GraphQL choreography; wrapped by ``push_book_to_hardcover``."""
    from app.models import Status  # noqa: PLC0415
    from integrations import (  # noqa: PLC0415
        hardcover_client,
        hardcover_mapping,
        signals,
    )
    from integrations.models import HardcoverIntegration  # noqa: PLC0415

    hc_book_id, hc_edition_id, _method = hardcover_mapping.resolve_book_id(
        book.item,
        token,
    )

    status_id = _map_yamtrack_status_to_hardcover(book.status)
    user_book = hardcover_client.get_user_book_for_book(hc_book_id, token)

    if user_book is None:
        # Book isn't in their Hardcover library yet — add it first.
        user_book_id = hardcover_client.insert_user_book(hc_book_id, status_id, token)
    else:
        user_book_id = user_book["id"]
        # Only update_user_book if status or rating actually drifted.
        updates = {}
        if user_book.get("status_id") != status_id:
            updates["status_id"] = status_id
        if book.score is not None:
            hc_rating = round(float(book.score) / 2 * 2) / 2  # 0..10 → 0..5 half-steps
            if user_book.get("rating") != hc_rating:
                updates["rating"] = hc_rating
        if updates:
            hardcover_client.update_user_book(user_book_id, updates, token)

    # Progress: update the latest unfinished read in place; otherwise open one.
    if book.progress or book.start_date or book.end_date:
        dates_payload = _build_dates_read_input(book, hc_edition_id)
        existing_reads = (user_book or {}).get("user_book_reads") or []
        active_read = next(
            (r for r in existing_reads if not r.get("finished_at")),
            None,
        )
        if active_read and book.status != Status.COMPLETED.value:
            hardcover_client.update_user_book_read(
                active_read["id"],
                dates_payload,
                token,
            )
        else:
            hardcover_client.insert_user_book_read(
                user_book_id,
                dates_payload,
                token,
            )

    # Stamp the row (via .update to skip post_save) so we recognise our
    # own echo if the inbound importer sees the change later.
    signals.mark_pushed(book.pk)
    HardcoverIntegration.objects.filter(pk=integration_id).update(
        last_pushed_at=timezone.now(),
        last_error="",
        last_error_at=None,
    )
    logger.info("HC push OK: Book %s → HC book %s.", book.pk, hc_book_id)


def _map_yamtrack_status_to_hardcover(yamtrack_status):
    """Yamtrack ``Status.value`` → Hardcover ``status_id`` integer."""
    from app.models import Status  # noqa: PLC0415

    mapping = {
        Status.PLANNING.value: 1,
        Status.IN_PROGRESS.value: 2,
        Status.COMPLETED.value: 3,
        Status.PAUSED.value: 4,
        Status.DROPPED.value: 5,
    }
    # Default to "Currently Reading" if the status is unfamiliar — better
    # than crashing, and the user can correct from Hardcover's UI.
    return mapping.get(yamtrack_status, 2)


def _build_dates_read_input(book, edition_id):
    """Construct the ``DatesReadInput`` GraphQL object for a Book row."""
    payload = {}
    if book.progress:
        payload["progress_pages"] = int(book.progress)
    if book.start_date:
        payload["started_at"] = book.start_date.date().isoformat()
    if book.end_date:
        payload["finished_at"] = book.end_date.date().isoformat()
    if edition_id:
        payload["edition_id"] = int(edition_id)
    return payload
