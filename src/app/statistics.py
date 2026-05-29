import calendar
import datetime
import heapq
import itertools
import logging
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.db import models
from django.db.models import (
    Prefetch,
    Q,
)
from django.utils import timezone

from app import config
from app.models import TV, BasicMedia, Episode, MediaManager, MediaTypes, Season, Status
from app.templatetags import app_tags

logger = logging.getLogger(__name__)


def get_user_media(user, start_date, end_date):
    """Get all media items and their counts for a user within date range."""
    media_models = [
        apps.get_model(app_label="app", model_name=media_type)
        for media_type in user.get_active_media_types()
    ]
    user_media = {}
    media_count = {"total": 0}

    # Cache the base episodes query
    base_episodes = None
    if TV in media_models or Season in media_models:
        if start_date is None and end_date is None:
            # No date filtering for "All Time"
            base_episodes = Episode.objects.filter(
                related_season__user=user,
            )
        else:
            base_episodes = Episode.objects.filter(
                related_season__user=user,
                end_date__range=(start_date, end_date),
            )

    for model in media_models:
        media_type = model.__name__.lower()
        queryset = None

        if model == TV:
            tv_ids = base_episodes.values_list(
                "related_season__related_tv",
                flat=True,
            ).distinct()
            queryset = TV.objects.filter(id__in=tv_ids).prefetch_related(
                Prefetch(
                    "seasons",
                    queryset=Season.objects.select_related(
                        "item",
                    ).prefetch_related(
                        Prefetch(
                            "episodes",
                            queryset=base_episodes.filter(
                                related_season__related_tv__in=tv_ids,
                            ),
                        ),
                    ),
                ),
            )
        elif model == Season:
            season_ids = base_episodes.values_list(
                "related_season",
                flat=True,
            ).distinct()
            queryset = Season.objects.filter(
                id__in=season_ids,
            ).prefetch_related(
                Prefetch("episodes", queryset=base_episodes),
            )
        # For other models, apply date filtering conditionally
        elif start_date is None and end_date is None:
            # No date filtering for "All Time"
            queryset = model.objects.filter(user=user)
        else:
            queryset = model.objects.filter(user=user).filter(
                # Case 1: Media has both start_date and end_date
                # Include if ranges overlap
                # (exclude if media ends before filter start or starts after filter end)
                (
                    Q(start_date__isnull=False)
                    & Q(end_date__isnull=False)
                    & ~(Q(end_date__lt=start_date) | Q(start_date__gt=end_date))
                )
                |
                # Case 2: Media only has start_date (end_date is null)
                # Include if start_date is within filter range
                (
                    Q(start_date__isnull=False)
                    & Q(end_date__isnull=True)
                    & Q(start_date__gte=start_date)
                    & Q(start_date__lte=end_date)
                )
                |
                # Case 3: Media only has end_date (start_date is null)
                # Include if end_date is within filter range
                (
                    Q(start_date__isnull=True)
                    & Q(end_date__isnull=False)
                    & Q(end_date__gte=start_date)
                    & Q(end_date__lte=end_date)
                ),
            )

        queryset = queryset.select_related("item")
        user_media[media_type] = queryset
        count = queryset.count()
        media_count[media_type] = count
        media_count["total"] += count

    logger.info(
        "%s - Retrieved media %s",
        user,
        "for all time" if start_date is None else f"from {start_date} to {end_date}",
    )
    return user_media, media_count


def get_media_type_distribution(media_count):
    """Get data formatted for Chart.js pie chart."""
    # Define colors for each media type
    # Format for Chart.js
    chart_data = {
        "labels": [],
        "datasets": [
            {
                "data": [],
                "backgroundColor": [],
            },
        ],
    }

    # Only include media types with counts > 0
    for media_type, count in media_count.items():
        if media_type != "total" and count > 0:
            # Format label with first letter capitalized
            label = app_tags.media_type_readable(media_type)
            chart_data["labels"].append(label)
            chart_data["datasets"][0]["data"].append(count)
            chart_data["datasets"][0]["backgroundColor"].append(
                config.get_stats_color(media_type),
            )
    return chart_data


def get_status_distribution(user_media):
    """Get status distribution for each media type within date range."""
    distribution = {}
    total_completed = 0
    # Define status order to ensure consistent stacking
    status_order = list(Status.values)
    for media_type, media_list in user_media.items():
        status_counts = dict.fromkeys(status_order, 0)
        counts = media_list.values("status").annotate(count=models.Count("id"))
        for count_data in counts:
            status_counts[count_data["status"]] = count_data["count"]
            if count_data["status"] == Status.COMPLETED.value:
                total_completed += count_data["count"]

        distribution[media_type] = status_counts

    # Format the response for charting
    return {
        "labels": [app_tags.media_type_readable(x) for x in distribution],
        "datasets": [
            {
                "label": status,
                "data": [
                    distribution[media_type][status] for media_type in distribution
                ],
                "background_color": get_status_color(status),
                "total": sum(
                    distribution[media_type][status] for media_type in distribution
                ),
            }
            for status in status_order
        ],
        "total_completed": total_completed,
    }


def get_status_pie_chart_data(status_distribution):
    """Get status distribution as a pie chart."""
    # Format for Chart.js pie chart
    chart_data = {
        "labels": [],
        "datasets": [
            {
                "data": [],
                "backgroundColor": [],
            },
        ],
    }

    # Process each status dataset
    for dataset in status_distribution["datasets"]:
        status_label = dataset["label"]
        status_count = dataset["total"]
        status_color = dataset["background_color"]

        # Only include statuses with counts > 0
        if status_count > 0:
            chart_data["labels"].append(status_label)
            chart_data["datasets"][0]["data"].append(status_count)
            chart_data["datasets"][0]["backgroundColor"].append(status_color)

    return chart_data


def get_score_distribution(user_media):
    """Get score distribution for each media type within date range."""
    distribution = {}
    total_scored = 0
    total_score_sum = 0

    top_rated = []
    top_rated_count = 14
    counter = itertools.count()  # Ensures stable sorting for equal scores
    score_range = range(11)

    for media_type, media_list in user_media.items():
        score_counts = dict.fromkeys(score_range, 0)
        scored_media = media_list.exclude(score__isnull=True).select_related("item")

        for media in scored_media:
            if len(top_rated) < top_rated_count:
                heapq.heappush(
                    top_rated,
                    (float(media.score), next(counter), media),
                )
            else:
                heapq.heappushpop(
                    top_rated,
                    (float(media.score), next(counter), media),
                )

            binned_score = int(media.score)
            score_counts[binned_score] += 1
            total_scored += 1
            total_score_sum += media.score

        distribution[media_type] = score_counts

    average_score = (
        round(total_score_sum / total_scored, 2) if total_scored > 0 else None
    )

    top_rated_media = [
        media for _, _, media in sorted(top_rated, key=lambda x: (-x[0], x[1]))
    ]

    top_rated_media = _annotate_top_rated_media(top_rated_media)

    return {
        "labels": [str(score) for score in score_range],
        "datasets": [
            {
                "label": app_tags.media_type_readable(media_type),
                "data": [distribution[media_type][score] for score in score_range],
                "background_color": config.get_stats_color(media_type),
            }
            for media_type in distribution
        ],
        "average_score": average_score,
        "total_scored": total_scored,
    }, top_rated_media


def _annotate_top_rated_media(top_rated_media):
    """Apply prefetch_related and annotate max_progress for top rated media."""
    if not top_rated_media:
        return top_rated_media

    # Group by media type to batch database operations
    media_by_type = {}
    for media in top_rated_media:
        media_type = media.item.media_type
        if media_type not in media_by_type:
            media_by_type[media_type] = []
        media_by_type[media_type].append(media)

    media_manager = MediaManager()

    for media_type, media_list in media_by_type.items():
        model = apps.get_model(app_label="app", model_name=media_type)
        media_ids = [media.id for media in media_list]

        # Fetch fresh instances with proper relationships and annotations
        queryset = model.objects.filter(id__in=media_ids)
        queryset = media_manager._apply_prefetch_related(queryset, media_type)
        media_manager.annotate_max_progress(queryset, media_type)

        prefetched_media_map = {media.id: media for media in queryset}

        # Replace original instances with enhanced ones
        for i, media in enumerate(top_rated_media):
            if media.item.media_type == media_type:
                top_rated_media[i] = prefetched_media_map[media.id]

    return top_rated_media


def get_status_color(status):
    """Get the color for the status of the media."""
    try:
        return config.get_status_stats_color(status)
    except KeyError:
        return "rgba(201, 203, 207)"


def get_record_listen_stats(item, user, top_n=10, recent_n=10, heatmap_days=365):
    """Build Koito-style listening stats for a single Record detail page.

    Returns a context dict with total_plays, total_minutes, unique_tracks,
    first_played, last_played, top_tracks (list of {track, plays}),
    recent_plays (latest N Play rows), and an activity heatmap with the
    same shape as ``get_activity_data`` so the existing calendar grid
    template can be reused.

    Returns ``None`` when there are no plays for this record so the
    template can skip the panel entirely.
    """
    from app.models import Play, Track  # noqa: PLC0415  avoids import cycle

    plays = Play.objects.filter(user=user, item=item)
    total_plays = plays.count()
    if total_plays == 0:
        return None

    total_seconds = (
        plays.aggregate(
            s=models.Sum("duration_seconds"),
        )["s"]
        or 0
    )
    # Fallback to an average 3:30 per track when no duration data is stored
    # (scrobbles always carry it; manual vinyl spins don't).
    if total_seconds == 0:
        total_seconds = total_plays * 210
    total_minutes = total_seconds // 60

    unique_tracks = plays.exclude(track__isnull=True).values("track").distinct().count()
    first_played = (
        plays.order_by("played_at").values_list("played_at", flat=True).first()
    )
    last_played = (
        plays.order_by("-played_at").values_list("played_at", flat=True).first()
    )

    top_track_rows = list(
        plays.exclude(track__isnull=True)
        .values("track")
        .annotate(play_count=models.Count("id"))
        .order_by("-play_count")[:top_n],
    )
    track_ids = [r["track"] for r in top_track_rows]
    track_map = {t.id: t for t in Track.objects.filter(id__in=track_ids)}
    top_tracks = [
        {"track": track_map[r["track"]], "plays": r["play_count"]}
        for r in top_track_rows
        if r["track"] in track_map
    ]

    recent_plays = list(
        plays.select_related("track").order_by("-played_at")[:recent_n],
    )

    end_dt = timezone.localtime()
    start_dt = end_dt - datetime.timedelta(days=heatmap_days)
    start_aligned = get_aligned_monday(start_dt)
    local_tz = timezone.get_current_timezone()

    counts_by_date = defaultdict(int)
    for ts in plays.filter(played_at__gte=start_aligned).values_list(
        "played_at",
        flat=True,
    ):
        counts_by_date[timezone.localtime(ts, local_tz).date()] += 1

    date_range = [
        start_aligned.date() + datetime.timedelta(days=x)
        for x in range((end_dt.date() - start_aligned.date()).days + 1)
    ]
    activity_days = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "count": counts_by_date.get(d, 0),
            "level": get_level(counts_by_date.get(d, 0)),
        }
        for d in date_range
    ]
    calendar_weeks = [activity_days[i : i + 7] for i in range(0, len(activity_days), 7)]

    months = []
    mondays_per_month = []
    current_month = date_range[0].strftime("%b") if date_range else None
    monday_count = 0
    for d in date_range:
        if d.weekday() == 0:
            m = d.strftime("%b")
            if current_month != m:
                months.append(current_month if monday_count > 1 else "")
                mondays_per_month.append(monday_count)
                current_month = m
                monday_count = 0
            monday_count += 1
    if monday_count > 1:
        months.append(current_month)
        mondays_per_month.append(monday_count)

    return {
        "total_plays": total_plays,
        "total_minutes": total_minutes,
        "unique_tracks": unique_tracks,
        "first_played": first_played,
        "last_played": last_played,
        "top_tracks": top_tracks,
        "recent_plays": recent_plays,
        "activity": {
            "calendar_weeks": calendar_weeks,
            "months": list(zip(months, mondays_per_month, strict=False)),
        },
    }


def get_music_stats(user, days=None, top_n=15):  # noqa: C901, PLR0912, PLR0915 — composition function with sequential well-named sections; splitting hurts readability
    """Aggregate the user's Play rows into a music dashboard payload.

    ``days`` limits the window (``None`` = all-time). Returns a dict with
    a ``has_data`` flag, summary stat cards, top artists/albums/tracks,
    plays-by-month, hour-of-day and weekday histograms, an activity
    heatmap (same shape as ``get_activity_data``), artist-discovery by
    month, and streak/milestone numbers.

    All aggregation is done in the database (Trunc/Extract) so it scales
    to large scrobble histories without loading rows into Python.
    """
    from django.db.models.functions import (  # noqa: PLC0415
        ExtractHour,
        ExtractIsoWeekDay,
        TruncDate,
        TruncMonth,
    )

    from app.models import Play  # noqa: PLC0415  avoids import cycle

    base = Play.objects.filter(user=user)
    now = timezone.localtime()
    qs = (
        base.filter(played_at__gte=now - datetime.timedelta(days=days))
        if days
        else base
    )

    total = qs.count()
    if total == 0:
        return {"has_data": False, "days": days}

    total_seconds = qs.aggregate(s=models.Sum("duration_seconds"))["s"] or 0
    if total_seconds == 0:
        total_seconds = total * 210  # 3:30 fallback for spins w/o duration
    listening_hours = round(total_seconds / 3600, 1)

    unique_artists = qs.exclude(artist="").values("artist").distinct().count()
    unique_tracks = qs.values("artist", "title").distinct().count()

    top_artists = list(
        qs.exclude(artist="")
        .values("artist")
        .annotate(plays=models.Count("id"))
        .order_by("-plays")[:top_n],
    )
    top_albums = list(
        qs.exclude(album="")
        .values("album", "artist")
        .annotate(plays=models.Count("id"))
        .order_by("-plays")[:top_n],
    )
    top_tracks = list(
        qs.exclude(title="")
        .values("title", "artist")
        .annotate(plays=models.Count("id"))
        .order_by("-plays")[:top_n],
    )

    month_rows = (
        qs.annotate(m=TruncMonth("played_at"))
        .values("m")
        .annotate(c=models.Count("id"))
        .order_by("m")
    )
    by_month = {
        "labels": [r["m"].strftime("%b %Y") for r in month_rows if r["m"]],
        "data": [r["c"] for r in month_rows if r["m"]],
    }

    hour_counts = [0] * 24
    for r in (
        qs.annotate(h=ExtractHour("played_at"))
        .values("h")
        .annotate(c=models.Count("id"))
    ):
        if r["h"] is not None:
            hour_counts[int(r["h"])] = r["c"]

    weekday_counts = [0] * 7
    for r in (
        qs.annotate(w=ExtractIsoWeekDay("played_at"))
        .values("w")
        .annotate(c=models.Count("id"))
    ):
        if r["w"] is not None:
            weekday_counts[int(r["w"]) - 1] = r["c"]

    day_counts = {}
    for r in (
        qs.annotate(d=TruncDate("played_at")).values("d").annotate(c=models.Count("id"))
    ):
        if r["d"]:
            day_counts[r["d"]] = r["c"]

    heatmap_days = days or 365
    start_aligned = get_aligned_monday(
        now - datetime.timedelta(days=heatmap_days),
    )
    date_range = [
        start_aligned.date() + datetime.timedelta(days=x)
        for x in range((now.date() - start_aligned.date()).days + 1)
    ]
    activity_days = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "count": day_counts.get(d, 0),
            "level": get_level(day_counts.get(d, 0)),
        }
        for d in date_range
    ]
    calendar_weeks = [activity_days[i : i + 7] for i in range(0, len(activity_days), 7)]
    months = []
    mondays_per_month = []
    current_month = date_range[0].strftime("%b") if date_range else None
    monday_count = 0
    for d in date_range:
        if d.weekday() == 0:
            mlabel = d.strftime("%b")
            if current_month != mlabel:
                months.append(current_month if monday_count > 1 else "")
                mondays_per_month.append(monday_count)
                current_month = mlabel
                monday_count = 0
            monday_count += 1
    if monday_count > 1:
        months.append(current_month)
        mondays_per_month.append(monday_count)

    current_streak, longest_streak = calculate_streaks(day_counts, now.date())
    busiest_day = None
    busiest_day_count = 0
    if day_counts:
        bd, bc = max(day_counts.items(), key=lambda kv: kv[1])
        busiest_day = bd.strftime("%b %d, %Y")
        busiest_day_count = bc

    # Artist discovery uses the user's full history (not the window) so the
    # "new artists per month" growth curve is meaningful.
    discovery = defaultdict(int)
    for r in (
        base.exclude(artist="").values("artist").annotate(first=models.Min("played_at"))
    ):
        if r["first"]:
            discovery[timezone.localtime(r["first"]).strftime("%Y-%m")] += 1
    disc_keys = sorted(discovery.keys())
    discoveries = {
        "labels": [
            datetime.datetime.strptime(k, "%Y-%m").strftime("%b %Y")  # noqa: DTZ007
            for k in disc_keys
        ],
        "data": [discovery[k] for k in disc_keys],
    }

    return {
        "has_data": True,
        "days": days,
        "cards": {
            "total_plays": total,
            "unique_artists": unique_artists,
            "unique_tracks": unique_tracks,
            "listening_hours": listening_hours,
            "active_days": len(day_counts),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "busiest_day": busiest_day,
            "busiest_day_count": busiest_day_count,
        },
        "top_artists": top_artists,
        "top_albums": top_albums,
        "top_tracks": top_tracks,
        "by_month": by_month,
        "by_hour": {
            "labels": [f"{h:02d}" for h in range(24)],
            "data": hour_counts,
        },
        "by_weekday": {
            "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "data": weekday_counts,
        },
        "discoveries": discoveries,
        "activity": {
            "calendar_weeks": calendar_weeks,
            "months": list(zip(months, mondays_per_month, strict=False)),
        },
    }


def get_record_stats(user):
    """Build chart data for the records list page.

    Returns ``None`` when the user has no records so callers can skip
    rendering the section entirely.
    """
    record_model = apps.get_model(app_label="app", model_name=MediaTypes.RECORD.value)
    qs = record_model.objects.filter(user=user).select_related("item")
    total = qs.count()
    if total == 0:
        return None

    owned = qs.filter(status=Status.COMPLETED.value).count()
    wanted = qs.filter(status=Status.PLANNING.value).count()

    return {
        "total": total,
        "owned_vs_want": _build_owned_vs_want(owned, wanted, total),
        "by_decade": _build_by_decade(qs),
        "top_artists": _build_top("item__artist", qs),
        "top_labels": _build_top("item__publisher", qs),
        "top_played": _build_top_played(user),
    }


def get_game_stats(user, top_limit=8):
    """Build the playtime stats panel for the games list page.

    Games store ``progress`` as minutes played, so unlike most media
    types their progress field carries a real runtime we can total and
    rank. Returns ``None`` when the user tracks no games so the caller
    can skip the panel. ``top_games`` carries a ``bar_pct`` relative to
    the most-played title for a no-canvas horizontal-bar list.
    """
    game_model = apps.get_model(app_label="app", model_name=MediaTypes.GAME.value)
    qs = game_model.objects.filter(user=user).select_related("item")
    total = qs.count()
    if total == 0:
        return None

    total_minutes = qs.aggregate(total=models.Sum("progress"))["total"] or 0
    completed = qs.filter(status=Status.COMPLETED.value).count()
    played_qs = qs.filter(progress__gt=0)
    played_count = played_qs.count()
    avg_minutes = round(total_minutes / played_count) if played_count else 0

    top_rows = list(
        played_qs.order_by("-progress").values("item__title", "progress")[:top_limit],
    )
    max_minutes = top_rows[0]["progress"] if top_rows else 0
    top_games = [
        {
            "title": row["item__title"],
            "minutes": row["progress"],
            "hours": round(row["progress"] / 60, 1),
            "bar_pct": round(row["progress"] / max_minutes * 100) if max_minutes else 0,
        }
        for row in top_rows
    ]

    return {
        "total": total,
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 1),
        "completed": completed,
        "played_count": played_count,
        "avg_minutes": avg_minutes,
        "avg_hours": round(avg_minutes / 60, 1),
        "top_games": top_games,
    }


def _build_top_played(user, days=90, limit=10):
    """Bar chart payload for the most-played records in the last ``days`` days.

    Counts both manual vinyl spins and ListenBrainz scrobbles that resolved
    to a Record's Item. Records with no plays in the window are excluded.
    """
    from app.models import Play  # noqa: PLC0415  avoids import cycle

    cutoff = timezone.now() - datetime.timedelta(days=days)
    rows = (
        Play.objects.filter(
            user=user,
            played_at__gte=cutoff,
            item__isnull=False,
            item__media_type=MediaTypes.RECORD.value,
        )
        .values("item_id", "item__artist", "item__title")
        .annotate(plays=models.Count("id"))
        .order_by("-plays")[:limit]
    )
    rows = list(rows)
    if not rows:
        return None

    color = config.get_stats_color(MediaTypes.RECORD.value)
    return {
        "labels": [
            (
                f"{r['item__artist']} - {r['item__title']}"
                if r["item__artist"]
                else r["item__title"] or f"Record #{r['item_id']}"
            )
            for r in rows
        ],
        "datasets": [
            {
                "label": "Plays",
                "data": [r["plays"] for r in rows],
                "background_color": color,
            },
        ],
    }


def _build_owned_vs_want(owned, wanted, total):
    """Donut chart payload for owned vs wanted records."""
    other = total - owned - wanted
    chart = {"labels": [], "datasets": [{"data": [], "backgroundColor": []}]}
    if owned:
        chart["labels"].append("Owned")
        chart["datasets"][0]["data"].append(owned)
        chart["datasets"][0]["backgroundColor"].append(
            config.get_status_stats_color(Status.COMPLETED.value),
        )
    if wanted:
        chart["labels"].append("Want")
        chart["datasets"][0]["data"].append(wanted)
        chart["datasets"][0]["backgroundColor"].append(
            config.get_status_stats_color(Status.PLANNING.value),
        )
    if other:
        chart["labels"].append("Other")
        chart["datasets"][0]["data"].append(other)
        chart["datasets"][0]["backgroundColor"].append("#6b7280")
    return chart


def _build_by_decade(qs):
    """Bar chart payload showing record count per decade."""
    rows = (
        qs.exclude(item__year__isnull=True)
        .values("item__year")
        .annotate(count=models.Count("id"))
    )
    buckets = defaultdict(int)
    for row in rows:
        decade = (row["item__year"] // 10) * 10
        buckets[decade] += row["count"]
    if not buckets:
        return None

    decades = sorted(buckets.keys())
    color = config.get_stats_color(MediaTypes.RECORD.value)
    return {
        "labels": [f"{d}s" for d in decades],
        "datasets": [
            {
                "label": "Records",
                "data": [buckets[d] for d in decades],
                "background_color": color,
            },
        ],
    }


def _build_top(field, qs, limit=10):
    """Bar chart payload for the top N values of an aggregation field.

    Skips empty strings (the field default) and splits comma-separated values
    so a release with multiple artists/labels counts toward each.
    """
    rows = (
        qs.exclude(**{f"{field}": ""})
        .exclude(**{f"{field}__isnull": True})
        .values(field)
    )
    counts = defaultdict(int)
    for row in rows:
        raw = row[field] or ""
        for chunk in (s.strip() for s in raw.split(",")):
            if chunk:
                counts[chunk] += 1
    if not counts:
        return None

    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:limit]
    color = config.get_stats_color(MediaTypes.RECORD.value)
    return {
        "labels": [name for name, _ in top],
        "datasets": [
            {
                "label": "Records",
                "data": [count for _, count in top],
                "background_color": color,
            },
        ],
    }


def get_timeline(user_media):
    """Build a timeline of media consumption organized by month-year."""
    timeline = defaultdict(list)

    # Process each media type
    for media_type, queryset in user_media.items():
        if media_type == MediaTypes.TV.value:
            continue
        for media in queryset:
            local_start_date = timezone.localdate(media.start_date)
            local_end_date = timezone.localdate(media.end_date)

            if media.start_date and media.end_date:
                # add media to all months between start and end
                current_date = local_start_date
                while current_date <= local_end_date:
                    year = current_date.year
                    month = current_date.month
                    month_name = calendar.month_name[month]
                    month_year = f"{month_name} {year}"

                    timeline[month_year].append(media)

                    # Move to next month
                    current_date += relativedelta(months=1)
                    current_date = current_date.replace(day=1)
            elif media.start_date:
                # If only start date, add to the start month
                year = local_start_date.year
                month = local_start_date.month
                month_name = calendar.month_name[month]
                month_year = f"{month_name} {year}"

                timeline[month_year].append(media)
            elif media.end_date:
                # If only end date, add to the end month
                year = local_end_date.year
                month = local_end_date.month
                month_name = calendar.month_name[month]
                month_year = f"{month_name} {year}"

                timeline[month_year].append(media)

    # Convert to sorted dictionary with media sorted by start date
    # Create a list sorted by year and month in reverse order
    sorted_items = []
    for month_year, media_list in timeline.items():
        month_name, year_str = month_year.split()
        year = int(year_str)
        month = list(calendar.month_name).index(month_name)
        sorted_items.append((month_year, media_list, year, month))

    # Sort by year and month in reverse chronological order
    sorted_items.sort(key=lambda x: (x[2], x[3]), reverse=True)

    # Create the final result dictionary
    result = {}
    for month_year, media_list, _, _ in sorted_items:
        # Sort the media list using our custom sort key
        result[month_year] = sorted(media_list, key=time_line_sort_key, reverse=True)
    return result


def time_line_sort_key(media):
    """Sort media items in the timeline."""
    if media.end_date is not None:
        return timezone.localdate(media.end_date)
    return timezone.localdate(media.start_date)


def get_activity_data(user, start_date, end_date):
    """Get daily activity counts for the last year."""
    if end_date is None:
        end_date = timezone.localtime()

    start_date_aligned = get_aligned_monday(start_date)

    combined_data = get_filtered_historical_data(start_date_aligned, end_date, user)

    # update start_date values from historical records if not provided
    if start_date is None:
        dates = [item["date"] for item in combined_data]
        start_date = datetime.datetime.combine(
            min(dates) if dates else timezone.localdate(),
            datetime.time.min,
        )
        start_date_aligned = get_aligned_monday(start_date)

    # Aggregate counts by date
    date_counts = {}
    for item in combined_data:
        date = item["date"]
        date_counts[date] = date_counts.get(date, 0) + item["count"]

    date_range = [
        start_date_aligned.date() + datetime.timedelta(days=x)
        for x in range((end_date.date() - start_date_aligned.date()).days + 1)
    ]

    # Calculate activity statistics
    most_active_day, day_percentage = calculate_day_of_week_stats(
        date_counts,
        start_date.date(),
    )
    current_streak, longest_streak = calculate_streaks(
        date_counts,
        end_date.date(),
    )

    # Create complete date range including padding days
    activity_data = [
        {
            "date": current_date.strftime("%Y-%m-%d"),
            "count": date_counts.get(current_date, 0),
            "level": get_level(date_counts.get(current_date, 0)),
        }
        for current_date in date_range
    ]

    # Format data into calendar weeks
    calendar_weeks = [activity_data[i : i + 7] for i in range(0, len(activity_data), 7)]

    # Generate months list with their Monday counts
    months = []
    mondays_per_month = []
    current_month = date_range[0].strftime("%b")
    monday_count = 0

    for current_date in date_range:
        if current_date.weekday() == 0:  # Monday
            month = current_date.strftime("%b")

            if current_month != month:
                if current_month is not None:
                    if monday_count > 1:
                        months.append(current_month)
                        mondays_per_month.append(monday_count)
                    else:
                        months.append("")
                        mondays_per_month.append(monday_count)
                current_month = month
                monday_count = 0

            monday_count += 1
    # For the last month
    if monday_count > 1:
        months.append(current_month)
        mondays_per_month.append(monday_count)

    return {
        "calendar_weeks": calendar_weeks,
        "months": list(zip(months, mondays_per_month, strict=False)),
        "stats": {
            "most_active_day": most_active_day,
            "most_active_day_percentage": day_percentage,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        },
    }


def get_aligned_monday(datetime_obj):
    """Get the Monday of the week containing the given date."""
    if datetime_obj is None:
        return None

    days_to_subtract = datetime_obj.weekday()  # 0=Monday, 6=Sunday
    return datetime_obj - datetime.timedelta(days=days_to_subtract)


def get_year_in_review(user, year):  # noqa: C901, PLR0912 — sequential composition of well-named blocks reads cleaner than 3 micro-helpers
    """Compose a year-end recap dataset for one user and one year.

    Mostly count-based metrics. Video/game runtime is still omitted (it
    would need a metadata-derived field on Item we don't store), but
    reading depth is included — pages read (a Book's progress field is
    its page count) and KOReader reading time. Designed to be cheap: one
    user_media fetch, one compute_sessions scan, and one activity_data
    fetch, all already optimized by the existing helpers.
    """
    tz = timezone.get_current_timezone()
    start_date = datetime.datetime(year, 1, 1, 0, 0, 0, tzinfo=tz)
    end_date = datetime.datetime(year, 12, 31, 23, 59, 59, tzinfo=tz)
    # Don't project past today when the user is reviewing the current year —
    # the activity heatmap and streaks shouldn't include phantom future cells.
    today_end = timezone.localtime()
    end_date = min(end_date, today_end)

    user_media, media_count = get_user_media(user, start_date, end_date)

    # Per-type completed counts. We use end_date (the completion stamp set
    # by Media.save()) inside the year window. For TV / Season, the helper
    # already restricts the prefetched episodes to the date range, so a
    # plain status==Completed count over the queryset is correct.
    completed_by_type = {}
    total_completed = 0
    for media_type, queryset in user_media.items():
        if media_type in (MediaTypes.TV.value, MediaTypes.SEASON.value):
            # Episode-driven types: count the in-range episodes instead of
            # the parent rows, so "100 episodes watched" reads honestly.
            episode_total = 0
            for parent in queryset:
                for season in (
                    [parent]
                    if media_type == MediaTypes.SEASON.value
                    else parent.seasons.all()
                ):
                    episode_total += sum(1 for _ in season.episodes.all())
            completed_by_type[media_type] = episode_total
            total_completed += episode_total
            continue
        completed = queryset.filter(status=Status.COMPLETED.value).count()
        completed_by_type[media_type] = completed
        total_completed += completed

    # Top rated — reuse the existing score-distribution helper, which
    # returns the top 14 items annotated with progress relationships.
    _, top_rated = get_score_distribution(user_media)
    top_rated = top_rated[:5]

    # Monthly completion counts, stacked by media type, in calendar order.
    # Each media type contributes one bar segment per month, derived from
    # the same date_field rule the calendar UI uses (end_date for non-
    # episodic types, the episode's end_date for TV / Season).
    monthly = {month: defaultdict(int) for month in range(1, 13)}
    for media_type, queryset in user_media.items():
        if media_type in (MediaTypes.TV.value, MediaTypes.SEASON.value):
            seasons_iter = (
                queryset
                if media_type == MediaTypes.SEASON.value
                else (s for parent in queryset for s in parent.seasons.all())
            )
            for season in seasons_iter:
                for episode in season.episodes.all():
                    if episode.end_date:
                        local = timezone.localtime(episode.end_date)
                        if local.year == year:
                            monthly[local.month][media_type] += 1
            continue
        for media in queryset.filter(status=Status.COMPLETED.value):
            if media.end_date:
                local = timezone.localtime(media.end_date)
                if local.year == year:
                    monthly[local.month][media_type] += 1

    monthly_completions = []
    for month_num in range(1, 13):
        by_type = dict(monthly[month_num])
        monthly_completions.append(
            {
                "month": calendar.month_abbr[month_num],
                "month_num": month_num,
                "by_type": by_type,
                "total": sum(by_type.values()),
            },
        )

    peak = max(monthly_completions, key=lambda m: m["total"])
    peak_month = peak if peak["total"] > 0 else None

    # Reading depth. Unlike video/game runtime (which needs metadata we
    # don't store), these are derivable today: a Book's progress field
    # *is* its page count, and KOReader sync events give real reading
    # time. Pages = final page count of books completed in the window;
    # time = inferred KOReader session minutes whose session start lands
    # in the window.
    pages_read = 0
    book_queryset = user_media.get(MediaTypes.BOOK.value)
    if book_queryset is not None:
        for book in book_queryset.filter(status=Status.COMPLETED.value):
            if book.end_date and timezone.localtime(book.end_date).year == year:
                pages_read += book.progress or 0

    from integrations.koreader_stats import (  # noqa: PLC0415
        aggregate_reading_time,
        compute_sessions,
    )

    year_sessions = [
        session
        for session in compute_sessions(user)
        if timezone.localtime(session.start).year == year
    ]
    reading_minutes, reading_session_count, _avg = aggregate_reading_time(year_sessions)

    activity = get_activity_data(user, start_date, end_date)
    activity_stats = activity.get("stats", {})

    media_types_seen = [mt for mt, count in completed_by_type.items() if count]

    return {
        "year": year,
        "start_date": start_date,
        "end_date": end_date,
        "completed_by_type": completed_by_type,
        "media_types_seen": media_types_seen,
        "total_completed": total_completed,
        "total_tracked": media_count.get("total", 0),
        "top_rated": top_rated,
        "monthly_completions": monthly_completions,
        "peak_month": peak_month,
        "pages_read": pages_read,
        "reading_minutes": reading_minutes,
        "reading_hours": round(reading_minutes / 60, 1),
        "reading_session_count": reading_session_count,
        "has_reading_stats": bool(pages_read or reading_minutes),
        "current_streak": activity_stats.get("current_streak", 0),
        "longest_streak": activity_stats.get("longest_streak", 0),
        "most_active_day": activity_stats.get("most_active_day"),
        "most_active_day_percentage": activity_stats.get(
            "most_active_day_percentage",
            0,
        ),
        "is_empty": total_completed == 0 and media_count.get("total", 0) == 0,
    }


def get_level(count):
    """Calculate intensity level (0-4) based on count."""
    thresholds = [0, 3, 6, 9]
    for i, threshold in enumerate(thresholds):
        if count <= threshold:
            return i
    return 4


def get_filtered_historical_data(start_date, end_date, user):
    """Return [{"date": datetime.date, "count": int}]."""
    historical_models = BasicMedia.objects.get_historical_models()
    local_tz = timezone.get_current_timezone()

    day_buckets = defaultdict(int)

    for model_name in historical_models:
        model = apps.get_model("app", model_name)

        qs = model.objects.filter(history_user_id=user)

        if start_date:
            qs = qs.filter(history_date__gte=start_date)
        if end_date:
            qs = qs.filter(history_date__lte=end_date)

        # We only need the timestamp, stream results to keep memory usage flat
        for ts in qs.values_list("history_date", flat=True).iterator(chunk_size=2_000):
            aware_ts = timezone.localtime(ts, local_tz)

            day_buckets[aware_ts.date()] += 1

    combined_data = [
        {"date": day, "count": count} for day, count in day_buckets.items()
    ]

    logger.info("%s - built historical data (%s rows)", user, len(combined_data))
    return combined_data


def calculate_day_of_week_stats(date_counts, start_date):
    """Calculate the most active day of the week based on activity frequency.

    Returns the day name and its percentage of total activity.
    """
    # Initialize counters for each day of the week
    day_counts = defaultdict(int)
    total_active_days = 0

    # Count occurrences of each day of the week where activity happened
    for date in date_counts:
        if date < start_date:
            continue
        if date_counts[date] > 0:
            day_name = date.strftime("%A")  # Get full day name
            day_counts[day_name] += 1
            total_active_days += 1

    if not total_active_days:
        return None, 0

    # Find the most active day
    most_active_day = max(day_counts.items(), key=lambda x: x[1])
    percentage = (most_active_day[1] / total_active_days) * 100

    return most_active_day[0], round(percentage)


def calculate_streaks(date_counts, end_date):
    """Calculate current and longest activity streaks."""
    # Get active dates and sort them in descending order (newest first)
    active_dates = sorted(
        [date for date, count in date_counts.items() if count > 0],
        reverse=True,
    )

    if not active_dates:
        return 0, 0

    longest_streak = 1
    streak_count = 1

    # Check if the most recent active date is today/end_date
    is_current = active_dates[0] == end_date

    current_streak = 1 if is_current else 0

    for i in range(1, len(active_dates)):
        # Check if this date is consecutive with the previous one
        if (active_dates[i - 1] - active_dates[i]).days == 1:
            streak_count += 1

            if is_current:
                current_streak += 1
        else:
            longest_streak = max(longest_streak, streak_count)
            streak_count = 1

            if is_current:
                is_current = False

    # Check final streak for longest calculation
    # needed if the last date is today/end_date
    longest_streak = max(longest_streak, streak_count)

    return current_streak, longest_streak
