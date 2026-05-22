"""TVmaze provider — used as a TMDB fallback for per-episode air dates.

TVmaze is free, keyless, and exposes a stable per-episode endpoint that's
useful when TMDB doesn't have an air_date populated for a brand-new or
obscure show. This module is not registered as a primary `Sources.*` so it
isn't user-facing — it's strictly enrichment.
"""

import logging

import requests
from django.core.cache import cache

from app.providers import services

logger = logging.getLogger(__name__)

base_url = "https://api.tvmaze.com"


def _lookup_show(imdb_id):
    """Return the TVmaze show dict for an IMDb ID, or None."""
    try:
        show = services.api_request(
            "tvmaze",
            "GET",
            f"{base_url}/lookup/shows",
            params={"imdb": imdb_id},
        )
    except requests.exceptions.RequestException as error:
        logger.warning("TVmaze lookup failed for %s: %s", imdb_id, error)
        return None
    if not isinstance(show, dict) or "id" not in show:
        return None
    return show


def _fetch_episodes(show_id):
    """Return the list of episode dicts for a TVmaze show id, or None on error."""
    try:
        return services.api_request(
            "tvmaze",
            "GET",
            f"{base_url}/shows/{show_id}/episodes",
        )
    except requests.exceptions.RequestException as error:
        logger.warning("TVmaze episodes failed for show %s: %s", show_id, error)
        return None


def episode_air_dates_by_imdb(imdb_id):
    """Return {(season_number, episode_number): "YYYY-MM-DD"} for the show.

    Returns an empty dict if TVmaze doesn't know the show or the request
    fails. Results are cached so a show is looked up at most once per
    CACHE_TIMEOUT.
    """
    if not imdb_id:
        return {}

    cache_key = f"tvmaze_ep_airdates_{imdb_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    show = _lookup_show(imdb_id)
    episodes = _fetch_episodes(show["id"]) if show else None

    air_dates = {}
    for ep in episodes or []:
        season = ep.get("season")
        number = ep.get("number")
        air = ep.get("airdate")
        if season is not None and number is not None and air:
            air_dates[(season, number)] = air

    cache.set(cache_key, air_dates)
    return air_dates
