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

    raw_artists = response.get("artists") or []
    artists_info = [
        {"id": str(a["id"]), "name": a["name"]}
        for a in raw_artists
        if a.get("id") and a.get("name")
    ]

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
        "artists": artists_info,
        "details": {
            "artist": format_artists(raw_artists),
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


def artist_lookup(name):
    """Resolve an artist name to a Discogs artist ID.

    Discogs treats artist names as fuzzy queries, so we ask for the top
    artist hit, take the first result, and return its numeric ID.
    Returns ``None`` when the search has no hits.
    """
    if not name:
        return None
    cache_key = f"{Sources.DISCOGS.value}_artist_lookup_{name.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None  # cached "" means "no match"; turn back into None

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/database/search",
            params={"q": name, "type": "artist", "per_page": 5},
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    results = response.get("results") or []
    # Prefer an exact (case-insensitive) name match, fall back to first hit.
    target = name.strip().lower()
    chosen = next(
        (r for r in results if (r.get("title") or "").strip().lower() == target),
        results[0] if results else None,
    )
    artist_id = str(chosen["id"]) if chosen and chosen.get("id") else ""

    cache.set(cache_key, artist_id)
    return artist_id or None


def artist_search(query, limit=6):
    """Search Discogs for artists matching ``query``.

    Returns a list of ``{name, image, profile_url}`` dicts so the search
    page can show artist matches alongside record results. The Discogs
    artist search returns ``title`` (display name including any " (2)"
    disambiguation), ``thumb`` (small avatar), and an ``id`` we don't
    use here — the artist details page is keyed by name, and the name
    in ``title`` is what users typed to find this match.

    Names with disambiguation suffixes (e.g. ``Beyoncé (2)``) are kept
    as-is so users can pick the right one; the artist details view does
    the same suffix-stripping on its end to resolve to a stable ID.
    """
    if not query or not query.strip():
        return []
    cache_key = (
        f"{Sources.DISCOGS.value}_artist_search_{query.strip().lower()}_{limit}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/database/search",
            params={"q": query, "type": "artist", "per_page": limit},
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError:
        return []

    out = []
    for r in response.get("results") or []:
        name = (r.get("title") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "image": r.get("cover_image") or r.get("thumb") or settings.IMG_NONE,
                "discogs_id": str(r.get("id") or ""),
            },
        )
    cache.set(cache_key, out)
    return out


def artist(artist_id):
    """Get artist metadata (name, image, profile, urls) from Discogs."""
    cache_key = f"{Sources.DISCOGS.value}_artist_{artist_id}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/artists/{artist_id}",
            params={},
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError as error:
        if error.response.status_code == requests.codes.not_found:
            services.raise_not_found_error(
                Sources.DISCOGS.value,
                artist_id,
                "artist",
            )
        handle_error(error)

    data = {
        "artist_id": str(response["id"]),
        "name": response.get("name") or f"Artist #{response['id']}",
        "image": pick_image(response),
        "profile": response.get("profile") or "",
        "source_url": response.get("uri")
        or f"https://www.discogs.com/artist/{artist_id}",
        "real_name": response.get("realname") or "",
        "name_variations": response.get("namevariations") or [],
        "members": [
            m.get("name")
            for m in (response.get("members") or [])
            if m.get("name")
        ],
        "urls": response.get("urls") or [],
    }
    cache.set(cache_key, data)
    return data


def artist_discography(artist_id):
    """Return the artist's discography as a list of release dicts.

    Each entry has: ``media_id`` (a Discogs release ID suitable for the
    record detail URL), ``master_id`` (when the entry is a master),
    ``title``, ``year``, ``image``, ``format``, ``label``, and
    ``role`` (kept so the template can flag side credits).

    Filters to ``role == "Main"`` (skipping Producer/Composer/etc. credits)
    and dedupes by master so each album shows once even when the artist
    has multiple pressings of the same release.

    Covers come from two endpoints merged by master_id: the artist's
    /releases listing gives us main_release IDs and year, the database
    search gives us a reliable cover_image (the /releases listing's thumb
    is empty for a large fraction of entries).
    """
    cache_key = f"{Sources.DISCOGS.value}_artist_discography_v2_{artist_id}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/artists/{artist_id}/releases",
            params={
                "per_page": 100,
                "sort": "year",
                "sort_order": "desc",
            },
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError as error:
        if error.response.status_code == requests.codes.not_found:
            services.raise_not_found_error(
                Sources.DISCOGS.value,
                artist_id,
                "artist",
            )
        handle_error(error)

    # Build cover map keyed by master_id from the search endpoint (which
    # returns cover_image / thumb reliably). Best-effort: if the lookup
    # fails for any reason, we fall back to the /releases listing thumbs.
    cover_by_master = _artist_master_covers(artist_id)

    raw = response.get("releases") or []
    out = []
    seen_masters = set()
    seen_releases = set()
    for entry in raw:
        if (entry.get("role") or "Main") != "Main":
            continue  # skip producer / composer / appearance credits

        entry_type = entry.get("type") or "release"
        if entry_type == "master":
            master_id = str(entry.get("id"))
            main_release = entry.get("main_release") or entry.get("id")
            if master_id in seen_masters:
                continue
            seen_masters.add(master_id)
            link_id = str(main_release)
        else:
            release_id = entry.get("id")
            master_id = ""
            if release_id in seen_releases:
                continue
            seen_releases.add(release_id)
            link_id = str(release_id)

        image = cover_by_master.get(master_id) or entry.get("thumb") or ""
        out.append(
            {
                "media_id": link_id,
                "master_id": master_id,
                "type": entry_type,
                "title": entry.get("title") or f"Discogs #{link_id}",
                "year": entry.get("year") or None,
                "image": image or settings.IMG_NONE,
                "format": entry.get("format") or "",
                "label": entry.get("label") or "",
                "role": entry.get("role") or "Main",
            },
        )

    out.sort(key=lambda r: (r["year"] or 0, r["title"]), reverse=True)
    cache.set(cache_key, out)
    return out


def _artist_master_covers(artist_id):
    """Return ``{master_id: cover_url}`` for masters credited to the artist.

    The /artists/<id>/releases endpoint's ``thumb`` field is empty for
    many entries, so we hit /database/search?artist=<name>&type=master
    once to grab cover_image / thumb URLs and merge them in. Soft-fails
    to an empty dict if the lookup errors out — the caller falls back to
    whatever thumbs the /releases listing provided.
    """
    try:
        artist_data = artist(artist_id)
    except services.ProviderAPIError:
        return {}
    name = (artist_data or {}).get("name")
    if not name:
        return {}

    try:
        response = services.api_request(
            Sources.DISCOGS.value,
            "GET",
            f"{BASE_URL}/database/search",
            params={
                "artist": name,
                "type": "master",
                "per_page": 100,
            },
            headers=auth_headers(),
        )
    except requests.exceptions.HTTPError:
        return {}

    covers = {}
    for r in response.get("results") or []:
        master_id = str(r.get("id") or "")
        image = r.get("cover_image") or r.get("thumb") or ""
        if master_id and image and image != settings.IMG_NONE:
            covers[master_id] = image
    return covers


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
    if len(nums) == 2:  # noqa: PLR2004 — mm:ss
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:  # noqa: PLR2004 — hh:mm:ss
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
