import logging
import time
from typing import Protocol

import requests
from defusedxml import ElementTree
from django.conf import settings
from pyrate_limiter import RedisBucket
from redis import Redis
from requests.adapters import HTTPAdapter
from requests_ratelimiter import LimiterAdapter, LimiterSession

from app.models import MediaTypes, Sources
from app.providers import (
    bgg,
    comicvine,
    discogs,
    hardcover,
    igdb,
    mal,
    mangaupdates,
    manual,
    openlibrary,
    tmdb,
)

logger = logging.getLogger(__name__)


class MetadataProvider(Protocol):
    """Contract every provider module satisfies at the dispatch seam.

    The shape is duck-typed: each provider module exposes the subset of
    these callables that applies to its media types. Return values are
    nested dicts keyed by the fields callers (views, models, templates)
    expect for that media type -- see e.g. ``tmdb.movie`` for the canonical
    field set. ``ProviderAPIError`` is the only failure callers must handle.
    """

    def search(self, query: str, page: int) -> dict:
        """Return a paginated dict of search results."""
        ...


class UnknownMediaTypeError(ValueError):
    """Raised by ``get_media_metadata`` / ``search`` for unhandled media_type."""


def get_redis_client():
    """Return a Redis client."""
    if settings.TESTING:
        import fakeredis  # noqa: PLC0415

        return fakeredis.FakeRedis()
    return Redis.from_url(settings.REDIS_URL)


redis_db = get_redis_client()
bucket_key = f"{settings.REDIS_PREFIX}_api" if settings.REDIS_PREFIX else "api"

session = LimiterSession(
    per_second=5,
    bucket_class=RedisBucket,
    bucket_kwargs={"redis": redis_db, "bucket_key": bucket_key},
)

session.mount("http://", HTTPAdapter(max_retries=3))
session.mount("https://", HTTPAdapter(max_retries=3))

session.mount(
    "https://api.myanimelist.net/v2",
    LimiterAdapter(per_minute=30),
)
session.mount(
    "https://graphql.anilist.co",
    LimiterAdapter(per_minute=85),
)
session.mount(
    "https://api.igdb.com/v4",
    LimiterAdapter(per_second=3),
)
session.mount(
    "https://api.tvmaze.com",
    LimiterAdapter(per_second=2),
)
session.mount(
    "https://comicvine.gamespot.com/api",
    LimiterAdapter(per_hour=190),
)
session.mount(
    "https://openlibrary.org",
    LimiterAdapter(per_minute=20),
)
session.mount(
    "https://api.hardcover.app/v1/graphql",
    LimiterAdapter(per_minute=50),
)
session.mount(
    "https://boardgamegeek.com/xmlapi2",
    LimiterAdapter(per_second=2),
)
session.mount(
    "https://api.discogs.com",
    LimiterAdapter(per_minute=55),
)
# OMDb free tier: 1,000 req/day. Be polite at 30/min so a bulk page render
# can't burn the daily budget in one minute.
session.mount(
    "https://www.omdbapi.com",
    LimiterAdapter(per_minute=30),
)


class ProviderAPIError(Exception):
    """Exception raised when a provider API fails to respond."""

    def __init__(self, provider, error, details=None):
        """Initialize the exception with the provider name."""
        self.provider = provider
        self.status_code = error.response.status_code
        try:
            provider = Sources(provider).label
        except ValueError:
            provider = provider.title()

        logger.error("%s error: %s", provider, error.response.text)

        message = (
            f"There was an error contacting the {provider} API "
            f"(HTTP {self.status_code})"
        )
        if details:
            message += f": {details}"
        message += ". Check the logs for more details."
        super().__init__(message)


def raise_not_found_error(provider, media_id, media_type="item"):
    """
    Raise a 404 ProviderAPIError for when a media item is not found.

    Args:
        provider: The provider source value (e.g., Sources.COMICVINE.value)
        media_id: The media ID that was not found
        media_type: The type of media (e.g., "comic", "game", "book")
    """
    error_msg = f"{media_type.capitalize()} with ID {media_id} not found"
    logger.error("%s: %s", provider, error_msg)

    # Create a mock 404 error response
    mock_response = type(
        "obj",
        (object,),
        {
            "status_code": 404,
            "text": error_msg,
        },
    )()
    mock_error = requests.exceptions.HTTPError(response=mock_response)

    raise ProviderAPIError(provider, mock_error, error_msg)


def api_request(
    provider,
    method,
    url,
    params=None,
    data=None,
    headers=None,
    response_format="json",
):
    """Make a request to the API and return the response.

    Args:
        provider: Provider identifier for error messages
        method: HTTP method ("GET" or "POST")
        url: Request URL
        params: Query params for GET, JSON body for POST
        data: Raw data for POST
        headers: Request headers
        response_format: "json" (default) or "xml" for XML parsing

    Returns:
        Parsed JSON dict or ElementTree for XML
    """
    try:
        request_kwargs = {
            "url": url,
            "headers": headers,
            "timeout": settings.REQUEST_TIMEOUT,
        }

        if method == "GET":
            request_kwargs["params"] = params
            request_func = session.get
        elif method == "POST":
            request_kwargs["data"] = data
            request_kwargs["json"] = params
            request_func = session.post

        response = request_func(**request_kwargs)
        response.raise_for_status()

        if response_format == "xml":
            return ElementTree.fromstring(response.text)
        return response.json()

    except requests.exceptions.HTTPError as error:
        error_resp = error.response
        status_code = error_resp.status_code

        # handle rate limiting
        if status_code == requests.codes.too_many_requests:
            seconds_to_wait = int(error_resp.headers.get("Retry-After", 5))
            logger.warning("Rate limited, waiting %s seconds", seconds_to_wait)
            time.sleep(seconds_to_wait + 3)
            logger.info("Retrying request")
            return api_request(
                provider,
                method,
                url,
                params=params,
                data=data,
                headers=headers,
                response_format=response_format,
            )

        raise error from None


# Each metadata handler takes
# ``(media_id, source, season_numbers, episode_number)`` and returns the
# provider's native metadata dict. Source-specific routing (Manga ->
# mangaupdates vs MAL; Book -> hardcover vs openlibrary) lives inside the
# handler, not the call site.


def _manga_metadata(mid, src, _sn, _en):
    if src == Sources.MANGAUPDATES.value:
        return mangaupdates.manga(mid)
    return mal.manga(mid)


def _book_metadata(mid, src, _sn, _en):
    if src == Sources.HARDCOVER.value:
        return hardcover.book(mid)
    return openlibrary.book(mid)


_METADATA_HANDLERS = {
    MediaTypes.ANIME.value: lambda mid, _src, _sn, _en: mal.anime(mid),
    MediaTypes.MANGA.value: _manga_metadata,
    MediaTypes.TV.value: lambda mid, _src, _sn, _en: tmdb.tv(mid),
    "tv_with_seasons": lambda mid, _src, sn, _en: tmdb.tv_with_seasons(mid, sn),
    MediaTypes.SEASON.value: lambda mid, _src, sn, _en: tmdb.tv_with_seasons(mid, sn)[
        f"season/{sn[0]}"
    ],
    MediaTypes.EPISODE.value: lambda mid, _src, sn, en: tmdb.episode(mid, sn[0], en),
    MediaTypes.MOVIE.value: lambda mid, _src, _sn, _en: tmdb.movie(mid),
    MediaTypes.GAME.value: lambda mid, _src, _sn, _en: igdb.game(mid),
    MediaTypes.BOOK.value: _book_metadata,
    MediaTypes.COMIC.value: lambda mid, _src, _sn, _en: comicvine.comic(mid),
    MediaTypes.BOARDGAME.value: lambda mid, _src, _sn, _en: bgg.boardgame(mid),
    MediaTypes.RECORD.value: lambda mid, _src, _sn, _en: discogs.record(mid),
}


def _manga_search(q, p, src):
    if src == Sources.MANGAUPDATES.value:
        return mangaupdates.search(q, p)
    return mal.search(MediaTypes.MANGA.value, q, p)


def _book_search(q, p, src):
    if src == Sources.OPENLIBRARY.value:
        return openlibrary.search(q, p)
    return hardcover.search(q, p)


_SEARCH_HANDLERS = {
    MediaTypes.MANGA.value: _manga_search,
    MediaTypes.ANIME.value: lambda q, p, _src: mal.search(MediaTypes.ANIME.value, q, p),
    MediaTypes.TV.value: lambda q, p, _src: tmdb.search(MediaTypes.TV.value, q, p),
    MediaTypes.MOVIE.value: lambda q, p, _src: tmdb.search(
        MediaTypes.MOVIE.value, q, p
    ),
    MediaTypes.SEASON.value: lambda q, p, _src: tmdb.search(MediaTypes.TV.value, q, p),
    MediaTypes.EPISODE.value: lambda q, p, _src: tmdb.search(MediaTypes.TV.value, q, p),
    MediaTypes.GAME.value: lambda q, p, _src: igdb.search(q, p),
    MediaTypes.BOOK.value: _book_search,
    MediaTypes.COMIC.value: lambda q, p, _src: comicvine.search(q, p),
    MediaTypes.BOARDGAME.value: lambda q, p, _src: bgg.search(q, p),
    MediaTypes.RECORD.value: lambda q, p, _src: discogs.search(q, p),
}


def get_media_metadata(
    media_type,
    media_id,
    source,
    season_numbers=None,
    episode_number=None,
):
    """Return the metadata for the selected media.

    Manual-source items are served by ``app.providers.manual``; every other
    source dispatches through ``_METADATA_HANDLERS``.
    """
    if source == Sources.MANUAL.value:
        if media_type == MediaTypes.SEASON.value:
            return manual.season(media_id, season_numbers[0])
        if media_type == MediaTypes.EPISODE.value:
            return manual.episode(media_id, season_numbers[0], episode_number)
        if media_type == "tv_with_seasons":
            media_type = MediaTypes.TV.value
        return manual.metadata(media_id, media_type)

    handler = _METADATA_HANDLERS.get(media_type)
    if handler is None:
        msg = f"No metadata handler registered for media_type={media_type!r}"
        raise UnknownMediaTypeError(msg)
    return handler(media_id, source, season_numbers, episode_number)


def search(media_type, query, page, source=None):
    """Search for media based on the query and return the results."""
    handler = _SEARCH_HANDLERS.get(media_type)
    if handler is None:
        msg = f"No search handler registered for media_type={media_type!r}"
        raise UnknownMediaTypeError(msg)
    return handler(query, page, source)
