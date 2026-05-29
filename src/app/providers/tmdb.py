import logging
from datetime import timedelta

import requests
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from app import helpers
from app.models import MediaTypes, Sources
from app.providers import omdb, services, tvmaze

logger = logging.getLogger(__name__)
base_url = "https://api.themoviedb.org/3"
base_params = {
    "api_key": settings.TMDB_API,
    "language": settings.TMDB_LANG,
}


def handle_error(error):
    """Handle TMDB API errors."""
    error_resp = error.response
    status_code = error_resp.status_code

    try:
        error_json = error_resp.json()
    except requests.exceptions.JSONDecodeError as json_error:
        logger.exception("Failed to decode JSON response")
        raise services.ProviderAPIError(Sources.TMDB.value, error) from json_error

    # Handle authentication errors
    if status_code == requests.codes.unauthorized:
        details = error_json.get("status_message")
        if details:
            # Remove trailing period if present
            details = details.rstrip(".")
            raise services.ProviderAPIError(Sources.TMDB.value, error, details)

    raise services.ProviderAPIError(
        Sources.TMDB.value,
        error,
    )


def get_external_links(external_ids, tmdb_id=None):
    """Build external links dictionary from TMDB external_ids response."""
    links = {}

    if external_ids.get("imdb_id"):
        links["IMDb"] = f"https://www.imdb.com/title/{external_ids['imdb_id']}/"

    if external_ids.get("tvdb_id"):
        links["TVDB"] = (
            f"https://www.thetvdb.com/dereferrer/series/{external_ids['tvdb_id']}"
        )

    if external_ids.get("wikidata_id"):
        links["Wikidata"] = (
            f"https://www.wikidata.org/wiki/{external_ids['wikidata_id']}"
        )

    # Only passed in for movies as Letterboxd seldom supports TV
    if tmdb_id:
        # https://letterboxd.com/about/film-data/
        # Letterboxd will redirect to the correct movie
        # as they source their data from TMDB
        links["Letterboxd"] = f"https://www.letterboxd.com/tmdb/{tmdb_id}"

    return links


def search(media_type, query, page):
    """Search for media on TMDB."""
    cache_key = f"search_{Sources.TMDB.value}_{media_type}_{query}_{page}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/search/{media_type}"

        params = {
            **base_params,
            "query": query,
            "page": page,
        }

        if settings.TMDB_NSFW:
            params["include_adult"] = "true"

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        results = [
            {
                "media_id": media["id"],
                "source": Sources.TMDB.value,
                "media_type": media_type,
                "title": get_title(media),
                "image": get_image_url(media["poster_path"]),
            }
            for media in response["results"]
        ]

        total_results = response["total_results"]
        per_page = 20  # TMDB always returns 20 results per page
        data = helpers.format_search_response(
            page,
            per_page,
            total_results,
            results,
        )

        cache.set(cache_key, data)

    return data


def find(external_id, external_source):
    """Search for media on TMDB."""
    cache_key = f"find_{Sources.TMDB.value}_{external_id}_{external_source}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/find/{external_id}"

        params = {
            **base_params,
            "external_source": external_source,
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        cache.set(cache_key, response)
        return response

    return data


def movie(media_id):
    """Return the metadata for the selected movie from The Movie Database."""
    cache_key = f"{Sources.TMDB.value}_{MediaTypes.MOVIE.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/movie/{media_id}"
        appends = [
            "recommendations",
            "external_ids",
            "credits",
            "watch/providers",
            "videos",
        ]
        params = {
            **base_params,
            "append_to_response": ",".join(appends),
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )

            if response.get("belongs_to_collection", {}) is not None and (
                collection_id := response.get("belongs_to_collection", {}).get("id")
            ):
                try:
                    collection_response = services.api_request(
                        Sources.TMDB.value,
                        "GET",
                        f"{base_url}/collection/{collection_id}",
                        params={**base_params},
                    )
                except requests.exceptions.HTTPError as error:
                    logger.warning("Failed to get collection: %s", error)
                    collection_response = {}
            else:
                collection_response = {}
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        # Filter out collection items from recommendations, to avoid duplicates
        collection_items = get_collection(collection_response)
        collection_ids = [item["media_id"] for item in collection_items]
        recommended_items = response.get("recommendations", {}).get("results", [])
        filtered_recommendations = [
            item for item in recommended_items if item["id"] not in collection_ids
        ]

        cast = response.get("credits", {}).get("cast", [])
        filtered_cast = [
            {
                "id": member.get("id"),
                "name": member.get("name"),
                "character": member.get("character"),
                "image": get_image_url(member.get("profile_path")),
            }
            for member in cast[:30]
        ]

        data = {
            "media_id": media_id,
            "source": Sources.TMDB.value,
            "source_url": f"https://www.themoviedb.org/movie/{media_id}",
            "media_type": MediaTypes.MOVIE.value,
            "title": response["title"],
            "max_progress": 1,
            "image": get_image_url(response["poster_path"]),
            "backdrop": get_backdrop_url(response.get("backdrop_path")),
            "synopsis": get_synopsis(response["overview"]),
            "genres": get_genres(response["genres"]),
            "score": get_score(response["vote_average"]),
            "score_count": response["vote_count"],
            "details": {
                "format": "Movie",
                "release_date": get_start_date(response["release_date"]),
                "status": response["status"],
                "runtime": get_readable_duration(response["runtime"]),
                **(
                    {"budget": format_money(response.get("budget"))}
                    if format_money(response.get("budget"))
                    else {}
                ),
                **(
                    {"revenue": format_money(response.get("revenue"))}
                    if format_money(response.get("revenue"))
                    else {}
                ),
                "studios": get_companies(response["production_companies"]),
                "country": get_country(response["production_countries"]),
                "languages": get_languages(response["spoken_languages"]),
            },
            "cast": filtered_cast,
            "total_cast_count": len(cast),
            "related": {
                collection_response.get("name", "collection"): collection_items,
                "recommendations": get_related(
                    filtered_recommendations,
                    MediaTypes.MOVIE.value,
                ),
            },
            "external_links": get_external_links(
                response.get("external_ids", {}), media_id
            ),
            "providers": response.get("watch/providers", {}).get("results", {}),
            "trailer": get_trailer(response.get("videos")),
        }

        imdb_id = response.get("external_ids", {}).get("imdb_id")
        data["details"].update(omdb.enrich(imdb_id))

        cache.set(cache_key, data)

    return data


def get_cached_seasons(media_id, season_numbers):
    """Check cache for seasons and return cached data and list of uncached seasons."""
    cached_data = {}
    uncached_seasons = []

    for season_number in season_numbers:
        season_cache_key = (
            f"{Sources.TMDB.value}_{MediaTypes.SEASON.value}_{media_id}_{season_number}"
        )
        season_data = cache.get(season_cache_key)
        if season_data:
            cached_data[f"season/{season_number}"] = season_data
        else:
            uncached_seasons.append(season_number)

    return cached_data, uncached_seasons


def enrich_season_with_tv_data(season_data, tv_data, media_id, season_number):
    """Add TV show metadata to season metadata."""
    season_data["media_id"] = media_id
    season_data["source_url"] = (
        f"https://www.themoviedb.org/tv/{media_id}/season/{season_number}"
    )
    season_data["title"] = tv_data["title"]
    season_data["tvdb_id"] = tv_data["tvdb_id"]
    season_data["external_links"] = tv_data["external_links"]
    season_data["genres"] = tv_data["genres"]
    if season_data["synopsis"] == "No synopsis available.":
        season_data["synopsis"] = tv_data["synopsis"]

    # Fill in missing episode air dates from TVmaze when TMDB has gaps
    # (common for upcoming/obscure shows). Single lookup per show; cached.
    imdb_id = tv_data.get("imdb_id")
    missing_air_dates = any(
        not ep.get("air_date") for ep in season_data.get("episodes", [])
    )
    if imdb_id and missing_air_dates:
        tvmaze_dates = tvmaze.episode_air_dates_by_imdb(imdb_id)
        if tvmaze_dates:
            for ep in season_data["episodes"]:
                if ep.get("air_date"):
                    continue
                fallback = tvmaze_dates.get((season_number, ep["episode_number"]))
                if fallback:
                    ep["air_date"] = fallback

    return season_data


def fetch_and_cache_seasons(media_id, season_numbers, tv_data):
    """Fetch uncached seasons from API and cache them."""
    url = f"{base_url}/tv/{media_id}"
    base_append = "recommendations,external_ids,watch/providers,credits"
    max_seasons_per_request = 8
    fetched_tv_data = tv_data
    result_data = {}

    for i in range(0, len(season_numbers), max_seasons_per_request):
        season_subset = season_numbers[i : i + max_seasons_per_request]
        append_text = ",".join(
            [
                f"season/{season},season/{season}/watch/providers"
                for season in season_subset
            ]
        )

        params = {
            **base_params,
            "append_to_response": f"{base_append},{append_text}",
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        # Cache TV metadata if we haven't fetched it yet
        if fetched_tv_data is None:
            fetched_tv_data = process_tv(response)
            tv_cache_key = f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}"
            cache.set(tv_cache_key, fetched_tv_data)

        # Process and cache each season
        for season_number in season_subset:
            season_key = f"season/{season_number}"
            if season_key not in response:
                msg = (
                    f"Season {season_number} not found in {Sources.TMDB.label} "
                    f"with ID {media_id}"
                )
                not_found_response = requests.Response()
                not_found_response.status_code = 404
                not_found_error = type("Error", (), {"response": not_found_response})
                raise services.ProviderAPIError(msg, error=not_found_error, details=msg)

            season_data = process_season(
                response[season_key], response[f"{season_key}/watch/providers"]
            )
            season_data = enrich_season_with_tv_data(
                season_data,
                fetched_tv_data,
                media_id,
                season_number,
            )

            cache.set(
                f"{Sources.TMDB.value}_{MediaTypes.SEASON.value}_{media_id}_{season_number}",
                season_data,
            )
            result_data[season_key] = season_data

    return result_data, fetched_tv_data


def tv_with_seasons(media_id, season_numbers):
    """Return the metadata for the tv show with seasons appended to the response."""
    if not season_numbers:
        return tv(media_id)

    tv_cache_key = f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}"
    tv_data = cache.get(tv_cache_key)

    cached_seasons, uncached_seasons = get_cached_seasons(media_id, season_numbers)

    if tv_data is None and not uncached_seasons:
        tv_data = tv(media_id)

    if uncached_seasons:
        fetched_seasons, fetched_tv_data = fetch_and_cache_seasons(
            media_id,
            uncached_seasons,
            tv_data,
        )

        if tv_data is None:
            tv_data = fetched_tv_data

        cached_seasons.update(fetched_seasons)

    return tv_data | cached_seasons


def tv(media_id):
    """Return the metadata for the selected tv show from The Movie Database."""
    cache_key = f"{Sources.TMDB.value}_{MediaTypes.TV.value}_{media_id}"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/tv/{media_id}"
        appends = "recommendations,external_ids,watch/providers,credits,videos"
        params = {
            **base_params,
            "append_to_response": appends,
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        data = process_tv(response)
        cache.set(cache_key, data)

    return data


def process_tv(response):
    """Process the metadata for the selected tv show from The Movie Database."""
    num_episodes = response["number_of_episodes"]
    next_episode = response.get("next_episode_to_air")
    last_episode = response.get("last_episode_to_air")
    cast = response.get("credits", {}).get("cast", []) or []
    filtered_cast = [
        {
            "id": member.get("id"),
            "name": member.get("name"),
            "character": member.get("character"),
            "image": get_image_url(member.get("profile_path")),
        }
        for member in cast[:30]
    ]
    imdb_id = response.get("external_ids", {}).get("imdb_id")
    omdb_enrichment = omdb.enrich(imdb_id)
    return {
        "media_id": response["id"],
        "source": Sources.TMDB.value,
        "source_url": f"https://www.themoviedb.org/tv/{response['id']}",
        "media_type": MediaTypes.TV.value,
        "title": response["name"],
        "max_progress": num_episodes,
        "image": get_image_url(response["poster_path"]),
        "backdrop": get_backdrop_url(response.get("backdrop_path")),
        "synopsis": get_synopsis(response["overview"]),
        "genres": get_genres(response["genres"]),
        "score": get_score(response["vote_average"]),
        "score_count": response["vote_count"],
        "details": {
            "format": "TV",
            "first_air_date": get_start_date(response["first_air_date"]),
            "last_air_date": response["last_air_date"],
            "status": response["status"],
            "seasons": response["number_of_seasons"],
            "episodes": num_episodes,
            "runtime": get_runtime_tv(response["episode_run_time"]),
            "studios": get_companies(response["production_companies"]),
            "country": get_country(response["production_countries"]),
            "languages": get_languages(response["spoken_languages"]),
            **omdb_enrichment,
        },
        "related": {
            "seasons": get_related(
                response["seasons"],
                MediaTypes.SEASON.value,
                response,
            ),
            "recommendations": get_related(
                response.get("recommendations", {}).get("results", []),
                MediaTypes.TV.value,
            ),
        },
        "tvdb_id": response.get("external_ids", {}).get("tvdb_id"),
        "imdb_id": imdb_id,
        "external_links": get_external_links(response.get("external_ids", {})),
        "last_episode_season": last_episode["season_number"] if last_episode else None,
        "next_episode_season": next_episode["season_number"] if next_episode else None,
        "providers": response.get("watch/providers", {}).get("results", {}),
        "trailer": get_trailer(response.get("videos")),
        "cast": filtered_cast,
        "total_cast_count": len(cast),
    }


def process_season(response, providers_response):
    """Process the metadata for the selected season from The Movie Database."""
    episodes = response["episodes"]
    num_episodes = len(episodes)

    runtimes = []
    total_runtime = 0
    score_count = 0

    for episode in episodes:
        if episode["runtime"] is not None:
            runtimes.append(episode["runtime"])
            total_runtime += episode["runtime"]
        score_count += episode["vote_count"]

    avg_runtime = (
        get_readable_duration(sum(runtimes) / len(runtimes)) if runtimes else None
    )
    total_runtime = get_readable_duration(total_runtime) if total_runtime else None

    return {
        "source": Sources.TMDB.value,
        "media_type": MediaTypes.SEASON.value,
        "season_title": response["name"],
        "max_progress": episodes[-1]["episode_number"] if episodes else 0,
        "image": get_image_url(response["poster_path"]),
        "season_number": response["season_number"],
        "synopsis": get_synopsis(response["overview"]),
        "score": get_score(response["vote_average"]),
        "score_count": score_count,
        "details": {
            "first_air_date": get_start_date(response["air_date"]),
            "last_air_date": get_end_date(response),
            "episodes": num_episodes,
            "runtime": avg_runtime,
            "total_runtime": total_runtime,
        },
        "episodes": response["episodes"],
        "providers": providers_response.get("results", {}),
    }


def get_format(media_type):
    """Return media_type capitalized."""
    if media_type == MediaTypes.TV.value:
        return "TV"
    return "Movie"


def get_image_url(path):
    """Return the image URL for the media."""
    # when no image, value from response is null
    # e.g movie: 445290
    if path:
        return f"https://image.tmdb.org/t/p/w500{path}"
    return settings.IMG_NONE


def get_backdrop_url(path):
    """Return a wide backdrop URL for hero use, or None if TMDB has no backdrop.

    Movies/shows without a backdrop_path get None (not IMG_NONE) so the
    detail-page hero can decide whether to render the image or fall back to
    the ambient gradient.
    """
    if path:
        return f"https://image.tmdb.org/t/p/w1280{path}"
    return None


def get_title(response):
    """Return the title for the media."""
    # tv shows have name instead of title
    try:
        return response["title"]
    except KeyError:
        return response["name"]


def get_trailer(videos_payload):
    """Pick the best YouTube trailer key from a TMDB videos payload.

    Preference order: official English-language trailer > any official
    trailer > any trailer > teaser. Returns {"source": "youtube", "key":
    "..."} or None when nothing usable is found.
    """
    if not videos_payload:
        return None
    candidates = [
        v
        for v in videos_payload.get("results", [])
        if v.get("site") == "YouTube" and v.get("key")
    ]
    if not candidates:
        return None

    def newest(filter_fn):
        matches = [v for v in candidates if filter_fn(v)]
        if not matches:
            return None
        # Newest published_at first; missing dates sort to the end.
        matches.sort(key=lambda v: v.get("published_at") or "", reverse=True)
        return matches[0]

    for filter_fn in (
        lambda v: (
            v.get("type") == "Trailer"
            and v.get("official")
            and v.get("iso_639_1") == "en"
        ),
        lambda v: v.get("type") == "Trailer" and v.get("official"),
        lambda v: v.get("type") == "Trailer",
        lambda v: v.get("type") == "Teaser",
    ):
        match = newest(filter_fn)
        if match:
            return {"source": "youtube", "key": match["key"]}
    return None


def get_start_date(date):
    """Return the start date for the media."""
    # when unknown date, value from response is empty string
    # e.g movie: 445290
    if date == "":
        return None
    return date


def get_end_date(response):
    """Return the last air date for the season."""
    if response["episodes"]:
        return response["episodes"][-1]["air_date"]

    return None


def get_synopsis(text):
    """Return the synopsis for the media."""
    # when unknown synopsis, value from response is empty string
    # e.g movie: 445290
    if text == "":
        return "No synopsis available."
    return text


def get_readable_duration(duration):
    """Convert duration in minutes to a readable format."""
    # if unknown movie runtime, value from response is 0
    # e.g movie: 274613
    if duration:
        hours, minutes = divmod(int(duration), 60)
        return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    return None


def get_runtime_tv(runtime):
    """Return the runtime for the tv show."""
    # when unknown runtime, value from response is empty list
    # e.g: tv:66672
    if runtime:
        return get_readable_duration(runtime[0])
    return None


def season_scores_count(response):
    """Return the scores count for the season."""
    return sum(episode["vote_count"] for episode in response["episodes"])


def get_genres(genres):
    """Return the genres for the media."""
    # when unknown genres, value from response is empty list
    # e.g tv: 24795
    if genres:
        return [genre["name"] for genre in genres]
    return None


def get_country(countries):
    """Return the production country for the media."""
    # when unknown production country, value from response is empty list
    # e.g tv: 24795
    if countries:
        return countries[0]["name"]
    return None


def get_languages(languages):
    """Return the languages for the media."""
    # when unknown spoken languages, value from response is empty list
    # e.g tv: 24795
    if languages:
        return [language["english_name"] for language in languages]
    return None


MONEY_BILLION = 1_000_000_000
MONEY_MILLION = 1_000_000
MONEY_THOUSAND = 1_000


def format_money(amount):
    """Format a USD figure as a human-readable string ($1.5B, $250M, $42K)."""
    if not amount or amount <= 0:
        return None
    if amount >= MONEY_BILLION:
        return f"${amount / MONEY_BILLION:.2f}B"
    if amount >= MONEY_MILLION:
        return f"${amount / MONEY_MILLION:.1f}M"
    if amount >= MONEY_THOUSAND:
        return f"${amount / MONEY_THOUSAND:.0f}K"
    return f"${amount:,}"


def get_companies(companies):
    """Return the production companies for the media."""
    # when unknown production companies, value from response is empty list
    # e.g tv: 24795
    if companies:
        return [company["name"] for company in companies[:3]]
    return None


def get_score(score):
    """Return the score for the media with one decimal place."""
    # when unknown score, value from response is 0.0

    return round(score, 1)


def get_related(related_medias, media_type, parent_response=None):
    """Return list of related media for the selected media."""
    related = []
    for media in related_medias:
        data = {
            "source": Sources.TMDB.value,
            "media_type": media_type,
            "image": get_image_url(media["poster_path"]),
        }
        if media_type == MediaTypes.SEASON.value:
            data["media_id"] = parent_response["id"]
            data["title"] = parent_response["name"]
            data["season_number"] = media["season_number"]
            data["season_title"] = media["name"]
            data["first_air_date"] = get_start_date(media["air_date"])
            data["max_progress"] = media["episode_count"]
        else:
            data["media_id"] = media["id"]
            data["title"] = get_title(media)
        related.append(data)
    return related


def get_collection(collection_response):
    """Format media collection list to match related media."""

    def date_key(media):
        date = media.get("release_date", "")
        if date is None or date == "":
            # If release date is unknown, sort by title after known releases
            title = get_title(media)
            date = f"9999-99-99-{title}"
        return date

    parts = sorted(collection_response.get("parts", []), key=date_key)
    return [
        {
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "image": get_image_url(media["poster_path"]),
            "media_id": media["id"],
            "title": get_title(media),
        }
        for media in parts
    ]


def filter_providers(all_providers, region):
    """Filter TMDB watch providers down to one region's flatrate + free chips.

    Returns ``None`` when the user has no region configured (so the caller
    can render the "set a region" prompt), or a dict with the providers
    list, the region's JustWatch deep-link, and the region code itself so
    the template can label the chip group clearly. The list may be empty
    when the title is tracked but not currently streaming anywhere
    flatrate/free in that region — callers should distinguish "no data
    yet" (None) from "no streaming options" (empty list).
    """
    if region == "":
        return None

    region_providers = (all_providers or {}).get(region, {}) or {}

    # Dedupe across flatrate + free; ignore rent/buy/ads — they're noisier
    # than they are useful when you're trying to answer "can I watch this
    # tonight without paying extra?".
    providers = {}
    for provider in (
        *region_providers.get("flatrate", []),
        *region_providers.get("free", []),
    ):
        providers[provider.get("provider_id")] = provider

    provider_list = sorted(
        providers.values(),
        key=lambda p: p.get("display_priority", 999),
    )
    for provider in provider_list:
        provider["image"] = get_image_url(provider.get("logo_path"))

    return {
        "providers": provider_list,
        "link": region_providers.get("link"),
        "region": region,
    }


def process_episodes(season_metadata, episodes_in_db):
    """Process the episodes for the selected season."""
    episodes_metadata = []

    # Convert the queryset to a dictionary for efficient lookups
    tracked_episodes = {}
    for ep in episodes_in_db:
        episode_number = ep.item.episode_number
        if episode_number not in tracked_episodes:
            tracked_episodes[episode_number] = []
        tracked_episodes[episode_number].append(ep)

    for episode in season_metadata["episodes"]:
        episode_number = episode["episode_number"]

        episodes_metadata.append(
            {
                "media_id": season_metadata["media_id"],
                "media_type": MediaTypes.EPISODE.value,
                "source": Sources.TMDB.value,
                "season_number": season_metadata["season_number"],
                "episode_number": episode_number,
                "air_date": episode["air_date"],  # when unknown, response returns null
                "image": get_image_url(episode["still_path"]),
                "title": episode["name"],
                "overview": episode["overview"],
                "history": tracked_episodes.get(episode_number, []),
                "runtime": get_readable_duration(episode["runtime"]),
                "runtime_minutes": episode["runtime"],
            },
        )
    return episodes_metadata


def find_next_episode(episode_number, episodes_metadata):
    """Find the next episode number."""
    # Find the current episode in the sorted list
    current_episode_index = None
    for index, episode in enumerate(episodes_metadata):
        if episode["episode_number"] == episode_number:
            current_episode_index = index
            break

    # If episode not found or it's the last episode, return None
    if current_episode_index is None or current_episode_index + 1 >= len(
        episodes_metadata,
    ):
        return None

    # Return the next episode number
    return episodes_metadata[current_episode_index + 1]["episode_number"]


def episode(media_id, season_number, episode_number):
    """Return the metadata for the selected episode from The Movie Database."""
    tv_metadata = tv_with_seasons(media_id, [season_number])
    season_metadata = tv_metadata[f"season/{season_number}"]

    for episode in season_metadata["episodes"]:
        if episode["episode_number"] == int(episode_number):
            return {
                "title": season_metadata["title"],
                "season_title": season_metadata["season_title"],
                "episode_title": episode["name"],
                "image": get_image_url(episode["still_path"]),
            }

    # Episode not found - throw ProviderAPIError
    msg = (
        f"Episode {episode_number} not found in season {season_number} "
        f"for {Sources.TMDB.label} with ID {media_id}"
    )
    # Create a new response object with 404 status
    not_found_response = requests.Response()
    not_found_response.status_code = 404
    # Set the error attribute to match what ProviderAPIError expects
    not_found_error = type("Error", (), {"response": not_found_response})
    raise services.ProviderAPIError(
        Sources.TMDB.value,
        error=not_found_error,
        details=msg,
    )


def watch_provider_regions():
    """Return the available watch provider regions from The Movie Database."""
    cache_key = f"{Sources.TMDB.value}_watch_provider_regions"
    data = cache.get(cache_key)

    if data is None:
        url = f"{base_url}/watch/providers/regions"
        params = {**base_params}

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except (requests.exceptions.HTTPError, services.ProviderAPIError):
            # This is metadata for an optional dropdown — if TMDB is
            # unreachable or the key is invalid, fail soft so the rest of
            # the preferences page still renders. Don't cache the error.
            logger.warning(
                "TMDB watch_provider_regions unavailable; "
                "preferences page will show Disabled-only.",
            )
            return [("", "Disabled")]

        data = [("", "Disabled")]
        regions = response.get("results", [])
        for region in sorted(regions, key=lambda r: r.get("english_name", "")):
            key = region.get("iso_3166_1")
            name = region.get("english_name")
            if key:
                if not name:
                    name = key
                data.append((key, name))

        cache.set(cache_key, data)

    return data


TMDB_MAX_PAGE = 500
DEFAULT_WATCH_REGION = "US"
STREAMING_WINDOW_DAYS = 180

MOVIE_BROWSE_CATEGORIES = (
    ("for_you", "For You"),
    ("popular", "Popular"),
    ("now_playing", "In Theaters"),
    ("streaming", "Streaming Now"),
    ("trending", "Trending"),
    ("upcoming", "Upcoming"),
    ("top_rated", "Top Rated"),
    ("hidden_gems", "Hidden Gems"),
    ("classics", "Classics"),
)

TV_BROWSE_CATEGORIES = (
    ("for_you", "For You"),
    ("popular", "Popular"),
    ("on_the_air", "On The Air"),
    ("airing_today", "Airing Today"),
    ("streaming", "Streaming Now"),
    ("trending", "Trending"),
    ("top_rated", "Top Rated"),
    ("hidden_gems", "Hidden Gems"),
    ("classics", "Classics"),
)

# Cutoff used by "classics" categories. Items released on or before this date
# are eligible. Picked as the millennium boundary so the bucket maps to
# "20th century cinema / TV" intuitively.
CLASSICS_CUTOFF = "1999-12-31"


def browse_categories(media_type):
    """Return the list of browse categories available for a media type."""
    raw = (
        TV_BROWSE_CATEGORIES
        if media_type == MediaTypes.TV.value
        else MOVIE_BROWSE_CATEGORIES
    )
    return [{"value": value, "label": label} for value, label in raw]


def browse_request_config(media_type, category, watch_region, genres=None):
    """Return the (url, extra_params) for a browse category.

    Unknown categories fall back to the "popular" endpoint so the page
    always renders something instead of erroring on a stale bookmark.

    ``genres`` is an optional iterable of TMDB genre ids. When non-empty,
    every category is routed through ``/discover`` (the only endpoint
    that accepts ``with_genres``) and simple categories are translated
    to their discover-equivalent sort/window params so the genre filter
    composes with the category instead of replacing it.
    """
    today = timezone.localdate()
    recent_floor = (today - timedelta(days=STREAMING_WINDOW_DAYS)).isoformat()

    if media_type == MediaTypes.MOVIE.value:
        simple = {
            "popular": "movie/popular",
            "now_playing": "movie/now_playing",
            "upcoming": "movie/upcoming",
            "top_rated": "movie/top_rated",
            "trending": "trending/movie/week",
        }
        default_path = "movie/popular"
        discover_path = "discover/movie"
        streaming_params = {
            "sort_by": "primary_release_date.desc",
            "with_watch_monetization_types": "flatrate",
            "watch_region": watch_region,
            "primary_release_date.gte": recent_floor,
            "primary_release_date.lte": today.isoformat(),
            "vote_count.gte": 20,
        }
        # Well-reviewed films that haven't hit the mainstream radar — vote
        # ceiling keeps blockbusters out, floor keeps unrated/spam out.
        hidden_gems_params = {
            "sort_by": "vote_average.desc",
            "vote_average.gte": 7.5,
            "vote_count.gte": 300,
            "vote_count.lte": 3000,
        }
        # Pre-2000 highly-rated films, ranked by score.
        classics_params = {
            "sort_by": "vote_average.desc",
            "primary_release_date.lte": CLASSICS_CUTOFF,
            "vote_average.gte": 7.5,
            "vote_count.gte": 500,
        }
        # Discover-equivalent params for the simple-endpoint categories,
        # used when a genre filter is active (with_genres only works on
        # /discover). Time windows roughly mirror TMDB's own definitions
        # of now_playing / upcoming so the user-facing semantics hold.
        now_playing_floor = (today - timedelta(days=45)).isoformat()
        upcoming_floor = (today + timedelta(days=1)).isoformat()
        simple_discover_overrides = {
            "popular": {
                "sort_by": "popularity.desc",
                "vote_count.gte": 50,
            },
            "now_playing": {
                "sort_by": "primary_release_date.desc",
                "primary_release_date.gte": now_playing_floor,
                "primary_release_date.lte": today.isoformat(),
                "with_release_type": "2|3",
            },
            "upcoming": {
                "sort_by": "primary_release_date.asc",
                "primary_release_date.gte": upcoming_floor,
            },
            "top_rated": {
                "sort_by": "vote_average.desc",
                "vote_count.gte": 300,
            },
            # Trending has no /discover equivalent — fall back to popularity
            # so the page still renders something coherent with a genre on.
            "trending": {
                "sort_by": "popularity.desc",
                "vote_count.gte": 50,
            },
        }
    else:
        simple = {
            "popular": "tv/popular",
            "on_the_air": "tv/on_the_air",
            "airing_today": "tv/airing_today",
            "top_rated": "tv/top_rated",
            "trending": "trending/tv/week",
        }
        default_path = "tv/popular"
        discover_path = "discover/tv"
        streaming_params = {
            "sort_by": "first_air_date.desc",
            "with_watch_monetization_types": "flatrate",
            "watch_region": watch_region,
            "first_air_date.gte": recent_floor,
            "first_air_date.lte": today.isoformat(),
            "vote_count.gte": 20,
        }
        hidden_gems_params = {
            "sort_by": "vote_average.desc",
            "vote_average.gte": 7.5,
            "vote_count.gte": 100,
            "vote_count.lte": 1500,
        }
        classics_params = {
            "sort_by": "vote_average.desc",
            "first_air_date.lte": CLASSICS_CUTOFF,
            "vote_average.gte": 7.5,
            "vote_count.gte": 100,
        }
        on_air_floor = (today - timedelta(days=7)).isoformat()
        on_air_ceiling = (today + timedelta(days=7)).isoformat()
        airing_today_date = today.isoformat()
        simple_discover_overrides = {
            "popular": {
                "sort_by": "popularity.desc",
                "vote_count.gte": 30,
            },
            "on_the_air": {
                "sort_by": "first_air_date.desc",
                "air_date.gte": on_air_floor,
                "air_date.lte": on_air_ceiling,
            },
            "airing_today": {
                "air_date.gte": airing_today_date,
                "air_date.lte": airing_today_date,
            },
            "top_rated": {
                "sort_by": "vote_average.desc",
                "vote_count.gte": 200,
            },
            "trending": {
                "sort_by": "popularity.desc",
                "vote_count.gte": 30,
            },
        }

    discover_overrides = {
        "streaming": streaming_params,
        "hidden_gems": hidden_gems_params,
        "classics": classics_params,
    }

    if genres:
        # with_genres requires /discover. Pick the category's discover
        # variant if it has one, else its simple-endpoint equivalent.
        # Missing keys (e.g., a brand-new category that forgot to add
        # an entry here) fall back to popularity-sorted.
        category_params = (
            discover_overrides.get(category)
            or simple_discover_overrides.get(category)
            or {"sort_by": "popularity.desc"}
        )
        extra_params = {
            **category_params,
            "with_genres": ",".join(str(g) for g in genres),
        }
        return f"{base_url}/{discover_path}", extra_params

    if category in discover_overrides:
        path, extra_params = discover_path, discover_overrides[category]
    else:
        path, extra_params = simple.get(category, default_path), {}

    return f"{base_url}/{path}", extra_params


def browse(media_type, category, page, watch_region=None, genres=None):
    """Return a paginated, browsable list of movies or TV shows from TMDB.

    ``genres`` is an optional list of TMDB genre ids that, when non-empty,
    routes the request through ``/discover`` with ``with_genres`` so the
    page is filtered server-side (AND semantics across multiple ids).
    """
    if not watch_region or watch_region == "UNSET":
        watch_region = DEFAULT_WATCH_REGION

    page = min(max(int(page), 1), TMDB_MAX_PAGE)

    genres_key = ",".join(str(g) for g in sorted(genres)) if genres else ""
    cache_key = (
        f"browse_{Sources.TMDB.value}_{media_type}_{category}_{watch_region}"
        f"_{page}_g={genres_key}"
    )
    data = cache.get(cache_key)
    if data is not None:
        return data

    url, extra_params = browse_request_config(
        media_type,
        category,
        watch_region,
        genres=genres,
    )
    params = {**base_params, "page": page, **extra_params}
    if settings.TMDB_NSFW:
        params["include_adult"] = "true"

    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=params,
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    genre_map = get_genre_map(media_type)
    results = [
        {
            "media_id": media["id"],
            "source": Sources.TMDB.value,
            "media_type": media_type,
            "title": get_title(media),
            "image": get_image_url(media.get("poster_path")),
            "original_language": media.get("original_language") or "",
            "genre_names": [
                genre_map[gid]
                for gid in media.get("genre_ids") or []
                if gid in genre_map
            ],
        }
        for media in response.get("results", [])
    ]

    data = {
        "page": page,
        "total_results": response.get("total_results", len(results)),
        "total_pages": min(response.get("total_pages", 1), TMDB_MAX_PAGE),
        "results": results,
    }

    cache.set(cache_key, data)
    return data


def _filter_by_genre_names(items, media_type, genres):
    """Drop items whose ``genre_names`` don't overlap any selected genre.

    No-op when ``genres`` is falsy. Translates the selected TMDB genre
    ids to their canonical names via ``get_genre_map`` so the filter
    matches against the same name vocabulary the enrichers attach.
    """
    if not genres:
        return items
    genre_map = get_genre_map(media_type)
    selected_names = {genre_map[g] for g in genres if g in genre_map}
    if not selected_names:
        return items
    return [r for r in items if selected_names & set(r.get("genre_names") or [])]


def get_genre_map(media_type):
    """Return ``{tmdb_genre_id: name}`` for the given media type.

    TMDB returns ``genre_ids`` (not names) on discover / popular /
    trending results, so we need a lookup table to translate. The
    /genre/movie/list and /genre/tv/list endpoints provide it. Cached
    for 7 days — TMDB's official genre list barely ever changes.
    """
    cache_key = f"tmdb_genre_map_{media_type}"
    data = cache.get(cache_key)
    if data is not None:
        return data

    path = (
        "genre/movie/list" if media_type == MediaTypes.MOVIE.value else "genre/tv/list"
    )
    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            f"{base_url}/{path}",
            params=base_params,
        )
    except requests.exceptions.HTTPError:
        return {}

    data = {entry["id"]: entry["name"] for entry in response.get("genres") or []}
    cache.set(cache_key, data, 60 * 60 * 24 * 7)
    return data


def for_you_browse(media_type, user, page, watch_region=None, genres=None):
    """Personalized browse list scored against the user's taste profile.

    Aggregates a candidate pool from the existing TMDB browse
    categories (popular + top_rated + trending), enriches each with
    genre names, attaches a match score from
    ``app.taste.attach_match_scores``, drops items the user already
    tracks or dismissed, and returns them sorted by descending match.

    Falls back to the "popular" list when the user lacks enough
    positive signal for the taste profile to be meaningful — same
    contract as ``browse()`` so the caller doesn't have to special-case
    cold-start users.

    ``genres`` (list of TMDB genre ids) further narrows the candidate
    pool to items tagged with at least one of those genres — applied
    after match-score sorting so the personalized order is preserved.
    """
    # Local imports to dodge circular-import cycles
    # (tmdb -> taste -> services -> tmdb).
    from app import taste  # noqa: PLC0415
    from app.models import DismissedItem  # noqa: PLC0415

    profile = taste.build_profile(user, media_type)
    if not taste.has_enough_signal(profile):
        if genres:
            return browse(media_type, "popular", page, watch_region, genres=genres)
        return browse(media_type, "popular", page, watch_region)

    genres_key = ",".join(str(g) for g in sorted(genres)) if genres else ""
    cache_key = (
        f"browse_{Sources.TMDB.value}_{media_type}_for_you_{user.id}"
        f"_{watch_region or DEFAULT_WATCH_REGION}_{page}_g={genres_key}"
    )
    data = cache.get(cache_key)
    if data is not None:
        return data

    # Pull a handful of pages from a few stable categories. Keeps total
    # API spend bounded; we'd rather re-rank a great candidate pool
    # than mint a 50-page personalized feed nobody scrolls past.
    candidate_sources = ("popular", "top_rated", "trending")
    seen = {}
    for category in candidate_sources:
        for src_page in (1, 2, 3):
            try:
                slice_data = browse(media_type, category, src_page, watch_region)
            except Exception:  # noqa: BLE001
                logger.warning("for_you: %s page %s failed", category, src_page)
                continue
            for r in slice_data.get("results") or []:
                seen.setdefault(r["media_id"], r)

    dismissed_ids = set(
        DismissedItem.objects.filter(
            user=user,
            source=Sources.TMDB.value,
            media_type=media_type,
        ).values_list("media_id", flat=True),
    )

    model = apps.get_model("app", media_type)
    owned_ids = set(
        model.objects.filter(
            user=user,
            item__source=Sources.TMDB.value,
            item__media_type=media_type,
        ).values_list("item__media_id", flat=True),
    )

    candidates = [
        r
        for mid, r in seen.items()
        if str(mid) not in dismissed_ids and str(mid) not in owned_ids
    ]

    candidates = _filter_by_genre_names(candidates, media_type, genres)

    for r in candidates:
        r["match_score"] = taste.score_item(profile, r.get("genre_names") or [])

    candidates.sort(key=lambda r: r.get("match_score", 0), reverse=True)

    page_size = 20
    total = len(candidates)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page), total_pages))
    start = (page - 1) * page_size
    end = start + page_size

    data = {
        "page": page,
        "total_results": total,
        "total_pages": total_pages,
        "results": candidates[start:end],
    }

    cache.set(cache_key, data, 60 * 30)  # 30 min — taste invalidations also clear
    return data


def get_changed_ids(media_type):
    """Return changed TMDB ids for the given media type over the last days."""
    url = f"{base_url}/{media_type}/changes"
    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=3)
    changed_ids = set()
    page = 1

    while True:
        params = {
            **base_params,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "page": page,
        }

        try:
            response = services.api_request(
                Sources.TMDB.value,
                "GET",
                url,
                params=params,
            )
        except requests.exceptions.HTTPError as error:
            handle_error(error)

        changed_ids.update(str(result["id"]) for result in response.get("results", []))

        total_pages = response.get("total_pages", 1)
        if page >= total_pages:
            break
        page += 1

    return changed_ids


def tv_changes():
    """Return changed TV ids from TMDB for the last days across all pages."""
    return get_changed_ids(MediaTypes.TV.value)


def movie_changes():
    """Return changed movie ids from TMDB for the last days across all pages."""
    return get_changed_ids(MediaTypes.MOVIE.value)


def _credit_release_date(credit):
    """Return the most appropriate release date for sorting credit entries."""
    return credit.get("release_date") or credit.get("first_air_date") or ""


def _process_credit(credit, role_kind):
    """Convert one raw TMDB combined-credit entry to our internal shape."""
    media_type = credit.get("media_type")
    if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        return None

    title = get_title(credit)
    if not title:
        return None

    release_date = _credit_release_date(credit)
    return {
        "media_id": credit["id"],
        "source": Sources.TMDB.value,
        "media_type": media_type,
        "title": title,
        "image": get_image_url(credit.get("poster_path")),
        "role_kind": role_kind,
        "role": credit.get("character") if role_kind == "cast" else credit.get("job"),
        "department": credit.get("department"),
        "release_date": release_date or None,
        "popularity": credit.get("popularity") or 0,
        "vote_average": credit.get("vote_average") or 0,
    }


def person(person_id):
    """Return profile + combined credits for a TMDB person."""
    cache_key = f"{Sources.TMDB.value}_person_{person_id}"
    data = cache.get(cache_key)

    if data is not None:
        return data

    url = f"{base_url}/person/{person_id}"
    params = {
        **base_params,
        "append_to_response": "combined_credits,external_ids",
    }

    try:
        response = services.api_request(
            Sources.TMDB.value,
            "GET",
            url,
            params=params,
        )
    except requests.exceptions.HTTPError as error:
        handle_error(error)

    combined = response.get("combined_credits", {}) or {}
    cast_credits = [
        processed
        for credit in combined.get("cast", []) or []
        if (processed := _process_credit(credit, "cast")) is not None
    ]
    crew_credits = [
        processed
        for credit in combined.get("crew", []) or []
        if (processed := _process_credit(credit, "crew")) is not None
    ]

    # De-duplicate crew entries that appear once per job. Keep the first
    # job title so the page still surfaces a representative role.
    seen_crew = {}
    for credit in crew_credits:
        key = (credit["media_id"], credit["media_type"])
        if key not in seen_crew:
            seen_crew[key] = credit
    crew_credits = list(seen_crew.values())

    image = get_image_url(response.get("profile_path"))

    data = {
        "id": response.get("id"),
        "name": response.get("name") or "",
        "image": image,
        "biography": (response.get("biography") or "").strip() or None,
        "birthday": response.get("birthday"),
        "deathday": response.get("deathday"),
        "place_of_birth": response.get("place_of_birth"),
        "known_for_department": response.get("known_for_department"),
        "also_known_as": response.get("also_known_as") or [],
        "homepage": response.get("homepage"),
        "source_url": f"https://www.themoviedb.org/person/{person_id}",
        "external_links": get_external_links(response.get("external_ids", {})),
        "cast_credits": cast_credits,
        "crew_credits": crew_credits,
    }

    cache.set(cache_key, data)
    return data
