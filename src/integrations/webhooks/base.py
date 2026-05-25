import logging

from django.core.cache import cache

import app
from app.models import MediaTypes
from app.providers import tvdb as tvdb_provider
from integrations.webhooks import recorder

logger = logging.getLogger(__name__)


class BaseWebhookProcessor:
    """Base class for webhook processors."""

    MEDIA_TYPE_MAPPING = {
        "Episode": MediaTypes.TV.value,
        "Movie": MediaTypes.MOVIE.value,
    }

    def process_payload(self, payload, user):
        """Process webhook payload."""
        raise NotImplementedError

    def _is_supported_event(self, event_type):
        """Check if event type is supported."""
        raise NotImplementedError

    def _is_played(self, payload):
        """Check if media is marked as played."""
        raise NotImplementedError

    def _extract_external_ids(self, payload):
        """Extract external IDs from payload."""
        raise NotImplementedError

    def _get_media_type(self, payload):
        """Get media type from payload."""
        raise NotImplementedError

    def _get_media_title(self, payload):
        """Get media title from payload."""
        raise NotImplementedError

    def _get_episode_number(self, payload):
        """Get episode number from payload."""
        raise NotImplementedError

    def _process_media(self, payload, user, ids):
        """Route processing based on media type."""
        media_type = self._get_media_type(payload)
        if not media_type:
            logger.debug("Ignoring unsupported media type")
            return

        title = self._get_media_title(payload)
        logger.info("Received webhook for %s: %s", media_type, title)

        if media_type == MediaTypes.TV.value:
            self._process_tv(payload, user, ids)
        elif media_type == MediaTypes.MOVIE.value:
            self._process_movie(payload, user, ids)

    def _process_tv(self, payload, user, ids):
        # Fetch the Kometa anime mapping once up front when anime detection
        # is enabled; the AniDB and TVDB branches below both consume it,
        # and calling _fetch_mapping_data twice doubled the cache lookups
        # for every TV webhook.
        mapping_data = self._fetch_mapping_data() if user.anime_enabled else None

        anidb_id = ids.get("anidb_id")
        if user.anime_enabled and anidb_id:
            matching_entry = mapping_data.get(anidb_id)
            episode_number = self._get_episode_number(payload)

            if not matching_entry:
                logger.info(
                    "AniDB ID %s not found in mapping, "
                    "falling through to TV processing",
                    anidb_id,
                )
            elif not episode_number:
                logger.warning(
                    "No episode number found for AniDB ID: %s",
                    anidb_id,
                )
            else:
                logger.info(
                    "Detected anime via AniDB ID: %s. Matching MAL ID: %s, Episode: %d",
                    anidb_id,
                    matching_entry["mal_id"],
                    episode_number,
                )
                self._handle_anime(
                    matching_entry["mal_id"],
                    episode_number,
                    payload,
                    user,
                )
                return

        tvdb_episode_id = ids.get("tvdb_id")
        if not tvdb_episode_id:
            logger.warning("No TVDB episode ID found for TV episode")
            return

        tvdb_episode = tvdb_provider.episode(int(tvdb_episode_id))
        if not tvdb_episode:
            logger.warning(
                "No TVDB episode metadata found for TVDB episode ID: %s",
                tvdb_episode_id,
            )
            return

        if user.anime_enabled:
            mal_id, episode_offset = self._get_mal_id_from_tvdb(
                mapping_data,
                tvdb_episode["series_id"],
                tvdb_episode["season_number"],
                tvdb_episode["episode_number"],
                absolute_episode_number=tvdb_episode["absolute_number"],
            )
            if mal_id:
                logger.info(
                    "Detected anime episode via MAL ID: %s, Episode: %d",
                    mal_id,
                    episode_offset,
                )
                self._handle_anime(mal_id, episode_offset, payload, user)
                return

        media_id, season_number, episode_number = self._find_tv_media_id(
            tvdb_episode_id
        )
        if not media_id:
            logger.warning(
                "No matching TMDB ID found for TVDB episode ID: %s", tvdb_episode_id
            )
            return

        logger.info(
            "Detected TV episode via TMDB ID: %s, Season: %d, Episode: %d",
            media_id,
            season_number,
            episode_number,
        )
        self._handle_tv_episode(media_id, season_number, episode_number, payload, user)

    def _process_movie(self, payload, user, ids):
        tmdb_id = ids["tmdb_id"]
        imdb_id = ids["imdb_id"]

        # Try to detect anime first if user has anime enabled
        if user.anime_enabled:
            mapping_data = self._fetch_mapping_data()
            mal_id = None
            source = None

            if tmdb_id:
                mal_id = self._get_mal_id_from_tmdb_movie(mapping_data, tmdb_id)
                source = "TMDB"

            if not mal_id and imdb_id:
                mal_id = self._get_mal_id_from_imdb(mapping_data, imdb_id)
                source = "IMDB"

            if mal_id:
                logger.info(
                    "Detected anime movie with MAL ID: %s (via %s)",
                    mal_id,
                    source,
                )
                self._handle_anime(mal_id, 1, payload, user)
                return

        # Handle as regular movie
        if tmdb_id:
            logger.info("Detected movie via TMDB ID: %s", tmdb_id)
            self._handle_movie(tmdb_id, payload, user)
        elif imdb_id:
            logger.debug("No TMDB ID found, looking up via IMDB ID: %s", imdb_id)
            response = app.providers.tmdb.find(imdb_id, "imdb_id")

            if response.get("movie_results"):
                media_id = response["movie_results"][0]["id"]
                logger.info("Found matching TMDB ID: %s", media_id)
                self._handle_movie(media_id, payload, user)
            else:
                logger.warning(
                    "No matching TMDB ID found for IMDB ID: %s",
                    imdb_id,
                )
        else:
            logger.warning("No TMDB or IMDB ID found for movie, skipping processing")

    def _find_tv_media_id(self, tvdb_episode_id):
        """Find TMDB TV episode metadata from a TVDB episode ID."""
        if tvdb_episode_id:
            response = app.providers.tmdb.find(tvdb_episode_id, "tvdb_id")
            if response.get("tv_episode_results"):
                result = response["tv_episode_results"][0]
                return (
                    result.get("show_id"),
                    result.get("season_number"),
                    result.get("episode_number"),
                )
        return None, None, None

    def _fetch_mapping_data(self):
        """Fetch anime mapping data with caching."""
        data = cache.get("anime_mapping_data")
        if data is None:
            url = "https://raw.githubusercontent.com/Kometa-Team/Anime-IDs/refs/heads/master/anime_ids.json"
            data = app.providers.services.api_request("GITHUB", "GET", url)
            # 24h matches CACHE_TIMEOUT for provider responses; without an
            # explicit timeout Django's default of 5 minutes refetches the
            # ~30KB JSON on every webhook burst.
            cache.set("anime_mapping_data", data, timeout=60 * 60 * 24)
        return data

    def _get_mal_id_from_tvdb(
        self,
        mapping_data,
        tvdb_id,
        season_number,
        episode_number,
        absolute_episode_number,
    ):
        """Find a MAL ID from Kometa's TVDB-based anime mappings.

        Kometa stores Anime-Lists absolute-order entries as ``tvdb_season = -1``.
        When available we prefer TVDB's absolute episode number for that fallback.
        For season 1, if TVDB does not provide one, the regular episode number is
        usually equivalent and can be used as a safe fallback.
        """

        def find_matching_entries(target_season):
            return [
                entry
                for entry in mapping_data.values()
                if entry.get("tvdb_id") == tvdb_id
                and entry.get("tvdb_season") == target_season
                and "mal_id" in entry
            ]

        def match_entries(entries, mapped_episode_number):
            if not entries or mapped_episode_number is None:
                return None, None

            entries.sort(key=lambda x: x.get("tvdb_epoffset", 0))
            for i, entry in enumerate(entries):
                current_offset = entry.get("tvdb_epoffset", 0)
                next_offset = (
                    entries[i + 1].get("tvdb_epoffset", float("inf"))
                    if i < len(entries) - 1
                    else float("inf")
                )

                if current_offset < mapped_episode_number <= next_offset:
                    mal_id = self._parse_mal_id(entry["mal_id"])
                    return mal_id, mapped_episode_number - current_offset

            return None, None

        mal_id, mapped_episode_number = match_entries(
            find_matching_entries(season_number),
            episode_number,
        )
        if mal_id:
            return mal_id, mapped_episode_number

        return match_entries(find_matching_entries(-1), absolute_episode_number)

    def _get_mal_id_from_tmdb_movie(self, mapping_data, tmdb_movie_id):
        """Find MAL ID from TMDB movie mapping."""
        for entry in mapping_data.values():
            if entry.get("tmdb_movie_id") == tmdb_movie_id and "mal_id" in entry:
                return self._parse_mal_id(entry["mal_id"])
        return None

    def _get_mal_id_from_imdb(self, mapping_data, imdb_id):
        """Find MAL ID from IMDB ID mapping."""
        for entry in mapping_data.values():
            if entry.get("imdb_id") == imdb_id and "mal_id" in entry:
                return self._parse_mal_id(entry["mal_id"])
        return None

    def _parse_mal_id(self, mal_id):
        """Parse MAL ID from potentially comma-separated string.

        mal_id: Either a single ID (int) or comma-separated string of IDs
        """
        if isinstance(mal_id, str) and "," in mal_id:
            return mal_id.split(",")[0].strip()
        return mal_id

    def _handle_movie(self, media_id, payload, user):
        """Handle movie playback event."""
        recorder.record_movie_play(media_id, self._is_played(payload), user)

    def _handle_tv_episode(
        self,
        media_id,
        season_number,
        episode_number,
        payload,
        user,
    ):
        """Handle TV episode playback event."""
        recorder.record_tv_episode_play(
            media_id,
            season_number,
            episode_number,
            self._is_played(payload),
            user,
        )

    def _handle_anime(self, media_id, episode_number, payload, user):
        """Handle anime playback event."""
        recorder.record_anime_play(
            media_id,
            episode_number,
            self._is_played(payload),
            user,
        )
