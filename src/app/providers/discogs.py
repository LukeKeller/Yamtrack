"""Discogs provider for vinyl record metadata.

Discogs is the canonical database for physical music releases. This provider
reads catalogue data only — per-user collection/wantlist data lives in the
importer module under integrations/imports/discogs.py.

Search restricts to format=Vinyl since Yamtrack tracks vinyl records, not
generic releases. Lookups go through the release endpoint
(/releases/{id}) which returns a single physical release with format,
year, label, and tracklist.
"""

import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache

from app import helpers
from app.models import MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

BASE_URL = "https://api.discogs.com"
USER_AGENT = "Yamtrack/1.0 +https://github.com/FuzzyGrim/Yamtrack"


def auth_headers():
    """Build auth headers for the catalogue endpoints.

    Discogs accepts a personal access token via the Authorization header.
    The header is omitted when no token is configured (rate limit drops to
    25/min unauthenticated, but search still works for public data).
    """
    headers = {"User-Agent": USER_AGENT}
    if settings.DISCOGS_API:
        headers["Authorization"] = f"Discogs token={settings.DISCOGS_API}"
    return headers


def handle_error(error):
    """Map Discogs HTTP errors to ProviderAPIError."""
    raise services.ProviderAPIError(Sources.DISCOGS.value, error)


def search(query, page):
    """Search Discogs releases for vinyl matching the query."""
    cache_key = (
        f"search_{Sources.DISCOGS.value}_{MediaTypes.RECORD.value}_{query}_{page}"
    )
    data = cache.get(cache_key)
    if data is not None:
        return data

    params = {
        "q": query,
        "type": "release",
        "format": "Vinyl",
        "per_page": settings.PER_PAGE,
        "page": page,
    }

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/database/search",
            params=params,
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    pagination = response.get("pagination", {})
    total_results = pagination.get("items", 0)
    raw_results = response.get("results") or []

    results = [
        {
            "media_id": str(item["id"]),
            "source": Sources.DISCOGS.value,
            "media_type": MediaTypes.RECORD.value,
            "title": item.get("title") or f"Discogs #{item['id']}",
            "image": item.get("cover_image") or settings.IMG_NONE,
        }
        for item in raw_results
        if item.get("id")
    ]

    data = helpers.format_search_response(
        page,
        settings.PER_PAGE,
        total_results,
        results,
    )

    cache.set(cache_key, data)
    return data


def record(media_id):
    """Get metadata for a single release from Discogs."""
    cache_key = f"{Sources.DISCOGS.value}_{MediaTypes.RECORD.value}_{media_id}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/releases/{media_id}",
            params={},
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError as error:
        if error.response.status_code == requests.codes.not_found:
            services.raise_not_found_error(
                Sources.DISCOGS.value,
                media_id,
                "record",
            )
        handle_error(error)

    title = format_title(response)
    image = pick_image(response)

    data = {
        "media_id": str(response["id"]),
        "source": Sources.DISCOGS.value,
        "source_url": response.get("uri") or f"https://www.discogs.com/release/{media_id}",
        "media_type": MediaTypes.RECORD.value,
        "title": title,
        "max_progress": None,
        "image": image,
        "synopsis": response.get("notes") or "No notes available.",
        "genres": response.get("genres") or [],
        "score": format_score(response.get("community", {}).get("rating")),
        "score_count": response.get("community", {}).get("rating", {}).get("count", 0),
        "details": {
            "artist": format_artists(response.get("artists")),
            "label": format_labels(response.get("labels")),
            "format": format_formats(response.get("formats")),
            "country": response.get("country"),
            "released": response.get("released") or response.get("year"),
            "styles": ", ".join(response.get("styles") or []) or None,
        },
    }

    cache.set(cache_key, data)
    return data


def tracks(media_id):
    """Return a list of track dicts for a Discogs release.

    Each dict has ``position`` (raw), ``side`` ("A".."Z" or ""),
    ``track_number`` (int or None), ``title``, ``artist`` (joined names
    when track-level credits exist), and ``duration_seconds``.

    Heading rows in the tracklist (``type_ == "heading"``) are skipped.
    Cached separately from ``record()`` so existing release-detail caches
    don't have to be invalidated.
    """
    cache_key = f"{Sources.DISCOGS.value}_{MediaTypes.RECORD.value}_{media_id}_tracks"
    data = cache.get(cache_key)
    if data is not None:
        return data

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/releases/{media_id}",
            params={},
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError as error:
        if error.response.status_code == requests.codes.not_found:
            services.raise_not_found_error(
                Sources.DISCOGS.value,
                media_id,
                "record",
            )
        handle_error(error)

    raw = response.get("tracklist") or []
    out = []
    for entry in raw:
        if entry.get("type_") and entry["type_"] != "track":
            continue  # skip heading/index rows
        position = (entry.get("position") or "").strip()
        if not position:
            continue  # unique constraint requires a position string
        side, num = parse_track_position(position)
        out.append(
            {
                "position": position,
                "side": side,
                "track_number": num,
                "title": entry.get("title") or "",
                "artist": format_artists(entry.get("artists")) or "",
                "duration_seconds": parse_duration_seconds(entry.get("duration") or ""),
            },
        )

    cache.set(cache_key, out)
    return out


def parse_track_position(position):
    """Parse a Discogs position string into (side_letter, track_number).

    Examples: "A1" -> ("A", 1); "B"  -> ("B", None); "1.2" -> ("", 1);
    "Vinyl A1" -> ("A", 1). Returns ("", None) if nothing matches.
    """
    if not position:
        return "", None
    match = re.search(r"([A-Za-z])?\s*(\d+)?", position)
    if not match:
        return "", None
    side = (match.group(1) or "").upper()
    num = int(match.group(2)) if match.group(2) else None
    return side, num


def parse_duration_seconds(value):
    """Parse a Discogs duration string ("3:45", "1:23:45") into total seconds."""
    if not value:
        return None
    parts = value.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def format_title(response):
    """Build "Artist - Title" from a Discogs release payload."""
    title = response.get("title") or f"Discogs #{response.get('id')}"
    artist = format_artists(response.get("artists"))
    if artist:
        return f"{artist} - {title}"
    return title


def format_artists(artists):
    """Join Discogs artist objects into a display string."""
    if not artists:
        return None
    return ", ".join(a.get("name") for a in artists if a.get("name"))


def format_labels(labels):
    """Format Discogs labels into a "Name (catno)" list."""
    if not labels:
        return None
    parts = []
    for label in labels:
        name = label.get("name")
        if not name:
            continue
        catno = label.get("catno")
        parts.append(f"{name} ({catno})" if catno else name)
    return ", ".join(parts) or None


def format_formats(formats):
    """Format Discogs format descriptors into a single string."""
    if not formats:
        return None
    parts = []
    for fmt in formats:
        name = fmt.get("name")
        descriptions = fmt.get("descriptions") or []
        qty = fmt.get("qty")
        chunk = name or ""
        if qty and qty != "1":
            chunk = f"{qty}x{chunk}"
        if descriptions:
            chunk = f"{chunk}, {', '.join(descriptions)}"
        if chunk:
            parts.append(chunk)
    return "; ".join(parts) or None


def format_score(rating):
    """Convert a Discogs community rating (0-5) to Yamtrack's 0-10 scale."""
    if not rating:
        return None
    average = rating.get("average")
    if not average:
        return None
    return round(float(average) * 2, 1)


def pick_image(response):
    """Return the primary cover image URL or the placeholder."""
    images = response.get("images") or []
    primary = next((img for img in images if img.get("type") == "primary"), None)
    if primary and primary.get("uri"):
        return primary["uri"]
    if images and images[0].get("uri"):
        return images[0]["uri"]
    return settings.IMG_NONE
