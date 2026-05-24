"""Find-or-create logic for a single play event.

Webhook processors parse a platform-specific payload and call into here
once the play has been resolved to a ``(media_type, media_id, ...)`` tuple.
The functions in this module own:

- ``Item`` get-or-create (per source / type / season / episode)
- ``Movie`` / ``TV`` / ``Season`` / ``Episode`` / ``Anime`` row creation
  with appropriate ``status`` / ``progress`` / ``start_date`` / ``end_date``
- Dedup of duplicate webhook fires (issue #689)

Keeping the logic here -- rather than spread across three webhook
subclasses and several inline blocks -- means the play-recording rules
sit at one seam. Importers and the music scrobble flow can call into
the same functions when they recreate the same effect.
"""

import logging

from django.utils import timezone

import app
from app.models import MediaTypes, Sources, Status

logger = logging.getLogger(__name__)

# Window (seconds) for treating a near-identical episode end_date as a
# duplicate webhook fire rather than a fresh play.
EPISODE_DEDUP_WINDOW_SECONDS = 5


def record_movie_play(media_id, played, user):
    """Create or update a Movie row for a play event.

    ``played`` is True for "finished playing" events, False for
    "started playing". A completed Movie is left alone (we never
    un-complete on a re-play).
    """
    movie_metadata = app.providers.tmdb.movie(media_id)
    movie_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        defaults={
            "title": movie_metadata["title"],
            "image": movie_metadata["image"],
        },
    )

    movie_instances = app.models.Movie.objects.filter(item=movie_item, user=user)
    current_instance = movie_instances.first()

    progress = 1 if played else 0
    now = timezone.now().replace(second=0, microsecond=0)

    if current_instance and current_instance.status != Status.COMPLETED.value:
        current_instance.progress = progress

        if played:
            current_instance.end_date = now
            current_instance.status = Status.COMPLETED.value
        elif current_instance.status != Status.IN_PROGRESS.value:
            current_instance.start_date = now
            current_instance.status = Status.IN_PROGRESS.value

        if current_instance.tracker.changed():
            current_instance.save()
            logger.info(
                "Updated existing movie instance to status: %s",
                current_instance.status,
            )
        else:
            logger.debug(
                "No changes detected for existing movie instance: %s",
                current_instance.item,
            )
    else:
        app.models.Movie.objects.create(
            item=movie_item,
            user=user,
            progress=progress,
            status=Status.COMPLETED.value if played else Status.IN_PROGRESS.value,
            start_date=now if not played else None,
            end_date=now if played else None,
        )
        logger.info(
            "Created new movie instance with status: %s",
            Status.COMPLETED.value if played else Status.IN_PROGRESS.value,
        )


def record_tv_episode_play(media_id, season_number, episode_number, played, user):
    """Create or update TV/Season/Episode rows for an episode play event."""
    tv_metadata = app.providers.tmdb.tv_with_seasons(media_id, [season_number])
    season_metadata = tv_metadata[f"season/{season_number}"]

    tv_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        defaults={
            "title": tv_metadata["title"],
            "image": tv_metadata["image"],
        },
    )

    tv_instance, tv_created = app.models.TV.objects.get_or_create(
        item=tv_item,
        user=user,
        defaults={"status": Status.IN_PROGRESS.value},
    )

    if tv_created:
        logger.info("Created new TV instance: %s", tv_metadata["title"])
    elif tv_instance.status != Status.IN_PROGRESS.value:
        tv_instance.status = Status.IN_PROGRESS.value
        tv_instance.save()
        logger.info(
            "Updated TV instance status to %s: %s",
            Status.IN_PROGRESS.value,
            tv_metadata["title"],
        )

    season_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.SEASON.value,
        season_number=season_number,
        defaults={
            "title": tv_metadata["title"],
            "image": season_metadata["image"],
        },
    )

    season_instance, season_created = app.models.Season.objects.get_or_create(
        item=season_item,
        user=user,
        related_tv=tv_instance,
        defaults={"status": Status.IN_PROGRESS.value},
    )

    if season_created:
        logger.info(
            "Created new season instance: %s S%02d",
            tv_metadata["title"],
            season_number,
        )
    elif season_instance.status != Status.IN_PROGRESS.value:
        season_instance.status = Status.IN_PROGRESS.value
        season_instance.save()
        logger.info(
            "Updated season instance status to %s: %s S%02d",
            Status.IN_PROGRESS.value,
            tv_metadata["title"],
            season_number,
        )

    episode_item = season_instance.get_episode_item(episode_number, season_metadata)

    if not played:
        logger.debug(
            "Episode not marked as played: %s S%02dE%02d",
            tv_metadata["title"],
            season_number,
            episode_number,
        )
        return

    now = timezone.now().replace(second=0, microsecond=0)
    latest_episode = (
        app.models.Episode.objects.filter(
            item=episode_item,
            related_season=season_instance,
        )
        .order_by("-end_date")
        .first()
    )

    # Webhooks sometimes fire multiple times for the same play (#689).
    if latest_episode and latest_episode.end_date:
        time_diff = abs((now - latest_episode.end_date).total_seconds())
        if time_diff < EPISODE_DEDUP_WINDOW_SECONDS:
            logger.debug(
                "Skipping duplicate episode record "
                "(time difference: %d seconds): %s S%02dE%02d",
                time_diff,
                tv_metadata["title"],
                season_number,
                episode_number,
            )
            return

    app.models.Episode.objects.create(
        item=episode_item,
        related_season=season_instance,
        end_date=now,
    )
    logger.info(
        "Marked episode as played: %s S%02dE%02d",
        tv_metadata["title"],
        season_number,
        episode_number,
    )


def record_anime_play(media_id, episode_number, played, user):
    """Create or update an Anime row for an episode play event."""
    anime_metadata = app.providers.mal.anime(media_id)
    anime_item, _ = app.models.Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
        defaults={
            "title": anime_metadata["title"],
            "image": anime_metadata["image"],
        },
    )

    anime_instances = app.models.Anime.objects.filter(item=anime_item, user=user)
    current_instance = anime_instances.first()

    if not played:
        episode_number = max(0, episode_number - 1)

    now = timezone.now().replace(second=0, microsecond=0)
    is_completed = episode_number == anime_metadata["max_progress"]
    status = Status.COMPLETED.value if is_completed else Status.IN_PROGRESS.value

    if current_instance and current_instance.status != Status.COMPLETED.value:
        current_instance.progress = episode_number

        if is_completed:
            current_instance.end_date = now
            current_instance.status = status
        elif current_instance.status != Status.IN_PROGRESS.value:
            current_instance.start_date = now
            current_instance.status = status

        if current_instance.tracker.changed():
            current_instance.save()
            logger.info(
                "Updated existing anime instance to status: %s with progress %d",
                current_instance.status,
                episode_number,
            )
        else:
            logger.debug(
                "No changes detected for existing anime instance: %s",
                current_instance.item,
            )
    else:
        app.models.Anime.objects.create(
            item=anime_item,
            user=user,
            progress=episode_number,
            status=status,
            start_date=now if not is_completed else None,
            end_date=now if is_completed else None,
        )
        logger.info(
            "Created new anime instance with status: %s and progress %d",
            status,
            episode_number,
        )
