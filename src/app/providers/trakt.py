"""Trakt browse provider.

Trakt has community-driven curation (most-watched, most-anticipated, box
office, ...) that complements TMDB's algorithmic popularity. Trakt items
embed TMDB ids, so the rest of Yamtrack can treat results as ordinary
TMDB items — we only use Trakt for the curation signal here, then back-
fill poster art from TMDB.

The import-side Trakt code lives in `integrations/imports/trakt.py`; this
module is read-only and used by the browse view.
"""

import concurrent.futures
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from app.models import MediaTypes, Sources
from app.providers import services, tmdb

logger = logging.getLogger(__name__)

TRAKT_BASE_URL = "https://api.trakt.tv"
TRAKT_PAGE_SIZE = 20
# Trakt lists are long but the tail is noise. Cap to keep pagination sane.
TRAKT_MAX_PAGE = 50
POSTER_FETCH_WORKERS = 8
# Posters change rarely; keep them around longer than the browse page cache.
POSTER_CACHE_TTL = 60 * 60 * 24 * 7
# Provider tag used for error messages — Trakt isn't in the Sources enum
# because we always materialize results as TMDB ids downstream.
PROVIDER_LABEL = "TRAKT"

MOVIE_BROWSE_CATEGORIES = (
    ("trending", "Trending"),
    ("popular", "Popular"),
    ("anticipated", "Anticipated"),
    ("watched_weekly", "Watched This Week"),
    ("played_weekly", "Played This Week"),
    ("collected_weekly", "Collected This Week"),
    ("boxoffice", "Box Office"),
    ("recommended_weekly", "Recommended"),
)

TV_BROWSE_CATEGORIES = (
    ("trending", "Trending"),
    ("popular", "Popular"),
    ("anticipated", "Anticipated"),
    ("watched_weekly", "Watched This Week"),
    ("played_weekly", "Played This Week"),
    ("collected_weekly", "Collected This Week"),
    ("recommended_weekly", "Recommended"),
)

_CATEGORY_PATHS = {
    "trending": "trending",
    "popular": "popular",
    "anticipated": "anticipated",
    "watched_weekly": "watched/weekly",
    "played_weekly": "played/weekly",
    "collected_weekly": "collected/weekly",
    "boxoffice": "boxoffice",
    "recommended_weekly": "recommended/weekly",
}


def is_configured():
    """Return True if Trakt browse can be used (client id present)."""
    return bool(settings.TRAKT_API)


def browse_categories(media_type):
    """Return the Trakt browse categories for a media type."""
    raw = (
        TV_BROWSE_CATEGORIES
        if media_type == MediaTypes.TV.value
        else MOVIE_BROWSE_CATEGORIES
    )
    return [{"value": value, "label": label} for value, label in raw]


def browse(media_type, category, page):
    """Return a paginated browse list from Trakt, normalized to TMDB ids."""
    if not is_configured():
        return _empty_page(page)

    page = min(max(int(page), 1), TRAKT_MAX_PAGE)

    cache_key = (
        f"browse_{Sources.TMDB.value}_via_trakt_{media_type}_{category}_{page}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    trakt_type = "movies" if media_type == MediaTypes.MOVIE.value else "shows"
    item_key = "movie" if media_type == MediaTypes.MOVIE.value else "show"
    path = _CATEGORY_PATHS.get(category, "popular")
    url = f"{TRAKT_BASE_URL}/{trakt_type}/{path}"
    params = {"page": page, "limit": TRAKT_PAGE_SIZE, "extended": "full"}
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": settings.TRAKT_API,
    }

    # services.api_request hides response headers, but Trakt's pagination
    # only comes through them. Use the shared rate-limited session directly.
    try:
        response = services.session.get(
            url,
            params=params,
            headers=headers,
            timeout=settings.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as error:
        logger.exception("Trakt browse failed for %s/%s", trakt_type, path)
        raise services.ProviderAPIError(PROVIDER_LABEL, error) from error

    total_pages = min(
        int(response.headers.get("X-Pagination-Page-Count", page)),
        TRAKT_MAX_PAGE,
    )
    total_results = int(response.headers.get("X-Pagination-Item-Count", 0))

    raw_results = response.json()
    items = list(_iter_tmdb_items(raw_results, item_key))
    _attach_tmdb_posters(items, media_type)

    results = [
        {
            "media_id": item["tmdb_id"],
            "source": Sources.TMDB.value,
            "media_type": media_type,
            "title": item["title"],
            "image": item["image"],
        }
        for item in items
    ]

    data = {
        "page": page,
        "total_results": total_results or len(results),
        "total_pages": max(total_pages, 1),
        "results": results,
    }
    cache.set(cache_key, data)
    return data


def _empty_page(page):
    return {"page": page, "total_results": 0, "total_pages": 1, "results": []}


def _iter_tmdb_items(raw_results, item_key):
    """Yield {tmdb_id, title} dicts from a mixed-shape Trakt response.

    Trakt wraps its payload in {watchers, movie}, {list_count, movie}, etc.
    for most endpoints but returns bare items for /popular. Items without a
    TMDB id are dropped since the rest of the app can't link to them.
    """
    for entry in raw_results:
        inner = entry.get(item_key, entry) if isinstance(entry, dict) else None
        if not inner:
            continue
        tmdb_id = (inner.get("ids") or {}).get("tmdb")
        if not tmdb_id:
            continue
        yield {"tmdb_id": tmdb_id, "title": inner.get("title", "")}


def _attach_tmdb_posters(items, media_type):
    """Fill `image` on each item by hitting TMDB in parallel."""
    if not items:
        return
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=POSTER_FETCH_WORKERS
    ) as executor:
        future_to_idx = {
            executor.submit(_fetch_tmdb_poster, item["tmdb_id"], media_type): idx
            for idx, item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            items[idx]["image"] = future.result()


def _fetch_tmdb_poster(tmdb_id, media_type):
    """Return a TMDB poster URL for one id, caching the path for a week."""
    cache_key = f"trakt_browse_poster_{media_type}_{tmdb_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    tmdb_path = "movie" if media_type == MediaTypes.MOVIE.value else "tv"
    url = f"{tmdb.base_url}/{tmdb_path}/{tmdb_id}"
    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=tmdb.base_params,
        )
    except requests.exceptions.HTTPError:
        logger.warning("TMDB poster lookup failed for %s/%s", tmdb_path, tmdb_id)
        return tmdb.get_image_url(None)

    image = tmdb.get_image_url(response.get("poster_path"))
    cache.set(cache_key, image, timeout=POSTER_CACHE_TTL)
    return image
