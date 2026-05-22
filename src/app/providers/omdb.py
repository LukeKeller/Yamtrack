"""OMDb provider — enrichment-only, keyed by IMDb ID.

OMDb is not used to identify or list media; it's called to decorate TMDB metadata
with the Rotten Tomatoes, Metacritic, and IMDb ratings, plus US box office, that
TMDB itself does not expose. If no OMDB_API key is configured this module
returns empty dicts so callers can no-op safely.
"""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from app.providers import services

logger = logging.getLogger(__name__)

base_url = "https://www.omdbapi.com/"

# OMDb's free tier is 1,000 req/day. We rely on Redis caching of the parsed
# enrichment dict so a given movie only hits the network once per CACHE_TIMEOUT.


def _is_enabled():
    return bool(getattr(settings, "OMDB_API", None))


_RATING_SOURCE_TO_KEY = {
    "Internet Movie Database": "imdb_rating",
    "Rotten Tomatoes": "rotten_tomatoes",
    "Metacritic": "metacritic",
}


def _fetch(imdb_id):
    """Return the parsed OMDb response or None on any failure."""
    params = {
        "i": imdb_id,
        "apikey": settings.OMDB_API,
        "tomatoes": "true",
    }
    try:
        response = services.api_request("omdb", "GET", base_url, params=params)
    except requests.exceptions.RequestException as error:
        logger.warning("OMDb request failed for %s: %s", imdb_id, error)
        return None

    if not isinstance(response, dict) or response.get("Response") == "False":
        return None
    return response


def _build_enrichment(response):
    """Pick out the fields we surface from a successful OMDb response."""
    enrichment = {}
    for rating in response.get("Ratings") or []:
        key = _RATING_SOURCE_TO_KEY.get(rating.get("Source", ""))
        value = rating.get("Value", "")
        if key and value:
            enrichment[key] = value

    for field, source_key in (("box_office", "BoxOffice"), ("awards", "Awards")):
        value = response.get(source_key)
        if value and value not in {"N/A", ""}:
            enrichment[field] = value
    return enrichment


def enrich(imdb_id):
    """Return rating / box office fields for a given IMDb ID.

    Always returns a dict — empty when OMDb isn't configured, the ID is
    missing, or the API errors. Callers can spread the result into their
    existing details dict.
    """
    if not imdb_id or not _is_enabled():
        return {}

    cache_key = f"omdb_enrich_{imdb_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = _fetch(imdb_id)
    if response is None:
        cache.set(cache_key, {})
        return {}

    enrichment = _build_enrichment(response)
    cache.set(cache_key, enrichment)
    return enrichment
