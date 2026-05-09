"""Import a user's Discogs vinyl library into Yamtrack.

Two endpoints feed the importer:

- ``/users/{username}/collection/folders/0/releases`` — owned records, mapped
  to ``Status.COMPLETED``.
- ``/users/{username}/wants`` — wantlist, mapped to ``Status.PLANNING``.

A Discogs personal access token authenticates the request and identifies
the user (no separate OAuth dance required). Pagination is by ``per_page``
(max 100) with ``page`` 1-indexed.
"""

import logging
from collections import defaultdict
from datetime import datetime

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

import app
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

DISCOGS_API_URL = "https://api.discogs.com"
USER_AGENT = "Yamtrack/1.0 +https://github.com/FuzzyGrim/Yamtrack"
PAGE_SIZE = 100
COLLECTION_FOLDER_ALL = 0


def auth_headers(token):
    """Build the headers for a Discogs API call with a personal access token."""
    return {
        "Authorization": f"Discogs token={token.strip()}",
        "User-Agent": USER_AGENT,
    }


def _request(method, url, token, params=None):
    """Run a Discogs request and surface auth errors as MediaImportError."""
    try:
        return services.api_request(
            Sources.DISCOGS.value,
            method,
            url,
            params=params,
            headers=auth_headers(token),
        )
    except requests.exceptions.HTTPError as error:
        status = error.response.status_code
        if status in (requests.codes.unauthorized, requests.codes.forbidden):
            msg = "Invalid or expired Discogs API token."
            raise MediaImportError(msg) from error
        if status == requests.codes.not_found:
            msg = (
                "Discogs returned 404 — the username on the token may be wrong "
                "or the collection is private."
            )
            raise MediaImportError(msg) from error
        raise


def get_username(token):
    """Validate the token and return the Discogs username."""
    data = _request("GET", f"{DISCOGS_API_URL}/oauth/identity", token)
    username = data.get("username")
    if not username:
        msg = "Could not look up Discogs account for this token."
        raise MediaImportError(msg)
    return username


def importer(token, user, mode, username=None):
    """Import a user's vinyl from Discogs.

    Args:
        token (str): Encrypted personal access token.
        user: Django user object to import into.
        mode (str): "new" or "overwrite".
        username (str, optional): Discogs username. Resolved via the token if
            not provided (kept for shared import_media signature parity).
    """
    return DiscogsImporter(token, user, mode, username).import_data()


class DiscogsImporter:
    """Import a user's vinyl collection and wantlist from Discogs."""

    def __init__(self, token, user, mode, username=None):
        """Initialize the importer.

        Args:
            token (str): Encrypted personal access token (decrypted on init).
            user: Django user object.
            mode (str): "new" or "overwrite".
            username (str, optional): Pre-resolved Discogs username.
        """
        self.token = helpers.decrypt(token)
        self.user = user
        self.mode = mode
        self.username = username or get_username(self.token)
        self.warnings = []

        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized Discogs importer for user %s (Discogs: %s, mode=%s)",
            user.username,
            self.username,
            mode,
        )

    def import_data(self):
        """Stream collection + wantlist and bulk-create records."""
        try:
            for entry in self._iter_collection():
                self._process_entry(entry, Status.COMPLETED.value)
            for entry in self._iter_wantlist():
                self._process_entry(entry, Status.PLANNING.value)
        except MediaImportError:
            raise
        except Exception as e:
            msg = "Error processing a Discogs entry."
            raise MediaImportUnexpectedError(msg) from e

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        deduplicated = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated

    def _iter_collection(self):
        url = (
            f"{DISCOGS_API_URL}/users/{self.username}"
            f"/collection/folders/{COLLECTION_FOLDER_ALL}/releases"
        )
        params = {"sort": "added", "sort_order": "desc"}
        yield from self._iter_paginated(url, params, "releases")

    def _iter_wantlist(self):
        url = f"{DISCOGS_API_URL}/users/{self.username}/wants"
        yield from self._iter_paginated(url, {}, "wants")

    def _iter_paginated(self, url, base_params, items_key):
        page = 1
        while True:
            params = {**base_params, "per_page": PAGE_SIZE, "page": page}
            data = _request("GET", url, self.token, params=params)

            items = data.get(items_key) or []
            if not items:
                return

            logger.info(
                "Fetched %s Discogs %s (page=%s)",
                len(items),
                items_key,
                page,
            )
            yield from items

            pagination = data.get("pagination") or {}
            total_pages = pagination.get("pages") or 1
            if page >= total_pages:
                return
            page += 1

    def _process_entry(self, entry, status):
        info = entry.get("basic_information") or {}
        release_id = entry.get("id") or info.get("id")
        if not release_id:
            return

        release_id_str = str(release_id)
        title = build_title(info, release_id_str)
        artist = build_artist(info)
        publisher = build_publisher(info)
        year = info.get("year") or None

        # Item metadata is shared across all users tracking this release. Always
        # upsert it (independent of "new"/"overwrite" mode, which only governs
        # per-user Records) so older Items get backfilled with artist/publisher/
        # year as soon as any user re-imports.
        item, created = app.models.Item.objects.get_or_create(
            media_id=release_id_str,
            source=Sources.DISCOGS.value,
            media_type=MediaTypes.RECORD.value,
            defaults={
                "title": title,
                "image": info.get("cover_image") or settings.IMG_NONE,
                "artist": artist,
                "publisher": publisher,
                "year": year,
            },
        )
        if not created and (
            (artist and not item.artist)
            or (publisher and not item.publisher)
            or (year and not item.year)
        ):
            app.models.Item.objects.filter(pk=item.pk).update(
                artist=artist or item.artist,
                publisher=publisher or item.publisher,
                year=year or item.year,
            )

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.RECORD.value,
            Sources.DISCOGS.value,
            release_id_str,
            self.mode,
        ):
            return

        rating = entry.get("rating")
        score = round(float(rating) * 2, 1) if rating else None

        instance = app.models.Record(
            item=item,
            user=self.user,
            score=score,
            progress=0,
            status=status,
            start_date=_parse_discogs_date(entry.get("date_added")),
            end_date=None,
            notes=entry.get("notes") or "",
        )

        date_added = parse_datetime(entry.get("date_added") or "")
        if date_added:
            instance._history_date = date_added

        self.bulk_media[MediaTypes.RECORD.value].append(instance)


def build_title(basic_info, release_id):
    """Compose an "Artist - Title" string for a Discogs release."""
    title = basic_info.get("title") or f"Discogs #{release_id}"
    artist_str = build_artist(basic_info)
    if artist_str:
        return f"{artist_str} - {title}"
    return title


def build_artist(basic_info):
    """Join the artists list from a Discogs basic_information block."""
    artists = basic_info.get("artists") or []
    return ", ".join(a.get("name") for a in artists if a.get("name"))


def build_publisher(basic_info):
    """Join Discogs labels into a comma-separated publisher string."""
    labels = basic_info.get("labels") or []
    names = []
    for label in labels:
        name = label.get("name")
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def _parse_discogs_date(raw):
    """Parse a Discogs ISO-8601 timestamp into an aware datetime."""
    if not raw:
        return None
    dt = parse_datetime(raw)
    if dt:
        return dt
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
