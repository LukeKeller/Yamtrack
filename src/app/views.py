import json
import logging
import re
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Max, prefetch_related_objects
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.utils.timezone import datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app import config, helpers, history_processor, taste
from app import statistics as stats
from app.forms import EpisodeForm, ManualItemForm, get_form_class
from app.models import (
    MOOD_LABELS,
    TV,
    BasicMedia,
    DismissedItem,
    Item,
    MediaTypes,
    Play,
    PlaySide,
    PlaySource,
    Record,
    Season,
    Sources,
    Status,
    Track,
    UserMessage,
)
from app.providers import discogs, manual, services, tmdb, trakt
from app.templatetags import app_tags
from events.models import Event
from events.views import build_calendar_context
from users.models import (
    DateFormatChoices,
    HomeSortChoices,
    MediaSortChoices,
    MediaStatusChoices,
    QuickWatchDateChoices,
)

logger = logging.getLogger(__name__)

_PALATE_MIN_SAMPLE = 5  # minimum history rows needed for the palate-cleanser nudge
_HIGH_SCORE_THRESHOLD = 8  # "8+ rated" cutoff on the person-stats panel


def _annotate_ready_count(media_list):
    """Flag episodic items that have released-but-unwatched units.

    Sets ``ready_count`` on each item: released units (``max_progress`` —
    e.g. aired episodes or published chapters) minus watched
    ``progress``, floored at zero. For a show you're caught up on this
    stays 0 until a new episode airs and ``max_progress`` ticks past your
    progress, so the rail's badge doubles as a "new episode is out"
    nudge rather than just a "you're mid-binge" count. Movies are skipped
    (their ``max_progress`` is always 1, so an unstarted movie would
    otherwise read as "1 ready").
    """
    for media in media_list:
        if media.item.media_type == MediaTypes.MOVIE.value:
            media.ready_count = 0
            continue
        max_progress = getattr(media, "max_progress", None) or 0
        watched = getattr(media, "progress", 0) or 0
        media.ready_count = max(0, max_progress - watched)


@require_GET
def home(request):
    """Home page with media items in progress and planning."""
    sort_by = request.user.update_preference("home_sort", request.GET.get("sort"))
    media_type_to_load = request.GET.get("load_media_type")
    status_to_load = request.GET.get("load_status", Status.IN_PROGRESS.value)
    items_limit = 14

    # If this is an HTMX request to load more items for a specific media type
    if request.headers.get("HX-Request") and media_type_to_load:
        list_by_type = BasicMedia.objects.get_home_status(
            user=request.user,
            status=status_to_load,
            sort_by=sort_by,
            items_limit=items_limit,
            specific_media_type=media_type_to_load,
        )
        context = {
            "media_list": list_by_type.get(media_type_to_load, []),
            "home_status": status_to_load,
        }
        return render(request, "app/components/home_grid.html", context)

    home_sections = []
    for status in (Status.IN_PROGRESS.value, Status.PLANNING.value):
        media_types = BasicMedia.objects.get_home_status(
            user=request.user,
            status=status,
            sort_by=sort_by,
            items_limit=items_limit,
        )
        home_sections.append(
            {
                "key": status,
                "id": slugify(status),
                "media_types": media_types,
                "count": sum(
                    media_list["total"] for media_list in media_types.values()
                ),
            },
        )

    # "Up next" rail — flatten the in-progress media types into a single list
    # sorted by the most-recently-progressed-on item, limited so the rail stays
    # one horizontal scroll on desktop.
    up_next = []
    in_progress = next(
        (s for s in home_sections if s["key"] == Status.IN_PROGRESS.value),
        None,
    )
    if in_progress:
        for info in in_progress["media_types"].values():
            up_next.extend(info["items"])
        up_next.sort(
            key=lambda m: (
                getattr(m, "progressed_at", None) or getattr(m, "created_at", None)
            ),
            reverse=True,
        )
        up_next = up_next[:12]
        _annotate_ready_count(up_next)

    context = {
        "home_sections": home_sections,
        "up_next": up_next,
        "watch_tonight": _watch_tonight(request.user),
        "recent_activity": _recent_activity(request.user, limit=8),
        "on_this_day": _on_this_day(request.user, limit=8),
        "stale_planning": _stale_planning(request.user, limit=5),
        "palate_cleanser": _palate_cleanser(request.user),
        "current_sort": sort_by,
        "sort_choices": HomeSortChoices.choices,
        "items_limit": items_limit,
        # Opts the mobile calendar list into the "anchor to today" mode
        # (cap height + scroll-to-today on render). The dedicated
        # /calendar page leaves the list unbounded so users can browse
        # months chronologically.
        "calendar_anchor_today": True,
        **build_calendar_context(request.user),
    }
    return render(request, "app/home.html", context)


def _match_date_field(model, date_field, user, month, day, today_year, limit):
    """Pull rows on (date_field.month, date_field.day) excluding today's year."""
    qs = (
        model.objects.filter(
            user=user,
            **{
                f"{date_field}__month": month,
                f"{date_field}__day": day,
            },
        )
        .exclude(**{f"{date_field}__year": today_year})
        .select_related("item")
        .order_by(f"-{date_field}")[: limit * 2]
    )
    return [
        {
            "item": media.item,
            "year": getattr(media, date_field).year,
            "date": getattr(media, date_field),
        }
        for media in qs
        if getattr(media, date_field) is not None
    ]


def _on_this_day(user, *, limit=8):
    """Items the user started or completed on this calendar date in past years.

    Reads each tracked subclass's start_date / end_date directly (cheap; the
    list is short and there's no full-table scan thanks to status filters
    elsewhere). Skips Episode — it has no per-episode tracking dates here —
    and re-targets Feb 29 to Feb 28 so leap-day items still surface annually.
    """
    today = timezone.localdate()
    compare_month, compare_day = today.month, today.day
    if (compare_month, compare_day) == (2, 29):  # leap-day → Feb 28 fallback
        compare_day = 28

    candidates = []
    for media_type in MediaTypes.values:
        if media_type == MediaTypes.EPISODE.value:
            continue
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        field_names = {f.name for f in model._meta.fields}
        for date_field, kind in (("end_date", "completed"), ("start_date", "started")):
            if date_field not in field_names:
                continue
            for row in _match_date_field(
                model,
                date_field,
                user,
                compare_month,
                compare_day,
                today.year,
                limit,
            ):
                row["kind"] = kind
                candidates.append(row)

    candidates.sort(key=lambda c: (c["date"], c["kind"]), reverse=True)
    # Deduplicate same item appearing as both started and completed today —
    # prefer "completed" since it's the bigger event.
    seen = set()
    deduped = []
    for c in candidates:
        key = (c["item"].pk, c["year"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped[:limit]


def _palate_cleanser(user, *, window_days=30, dominance=0.7):
    """Suggest a Planning item from a different media type when one dominates.

    If a single media_type accounts for more than ``dominance`` of the user's
    recent history (last ``window_days``) and there's at least a minimal
    sample, returns one Planning item from a different type. Returns
    ``None`` otherwise.
    """
    threshold = timezone.now() - timedelta(days=window_days)
    counts = {}
    total = 0
    for name in BasicMedia.objects.get_historical_models():
        model = apps.get_model("app", name)
        live_type = name.replace("historical", "")
        n = model.objects.filter(
            history_user_id=user.id,
            history_date__gte=threshold,
        ).count()
        if n:
            counts[live_type] = n
            total += n

    if total < _PALATE_MIN_SAMPLE:
        return None
    dominant_type, dominant_count = max(counts.items(), key=lambda kv: kv[1])
    if dominant_count / total < dominance:
        return None

    # Pick one Planning item from a different media_type.
    for media_type in MediaTypes.values:
        if media_type in (MediaTypes.EPISODE.value, dominant_type):
            continue
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        field_names = {f.name for f in model._meta.fields}
        if "status" not in field_names:
            continue
        candidate = (
            model.objects.filter(user=user, status=Status.PLANNING.value)
            .select_related("item")
            .order_by("?")
            .first()
        )
        if candidate:
            return {
                "item": candidate.item,
                "dominant_type": dominant_type,
                "dominant_pct": round(dominant_count / total * 100),
            }
    return None


_WATCH_TONIGHT_CANDIDATE_CAP = 30  # how many recent Planning rows we look at
_WATCH_TONIGHT_LIMIT = 8  # rendered rail length


def _recent_planning_candidates(user, *, cap):
    """Recent Planning movies + TV (TMDB only) for the streaming rail.

    Returns a list of ``(media_type, media)`` tuples. TMDB-only because
    only TMDB metadata carries watch-provider data today.
    """
    candidates = []
    for media_type in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        qs = (
            model.objects.filter(
                user=user,
                status=Status.PLANNING.value,
                item__source=Sources.TMDB.value,
            )
            .select_related("item")
            .order_by("-created_at")[:cap]
        )
        candidates.extend((media_type, media) for media in qs)
    return candidates


def _releases_today_candidates(user):
    """In progress / Planning movies + TV (TMDB only) with a release event today.

    Returns a list of ``(media_type, media)`` tuples. Episodes air against
    the season item, so we collect TV media via the season's parent media_id.
    """
    today = timezone.localdate()
    today_events = Event.objects.get_user_events(user, today, today)

    movie_media_ids = set()
    tv_media_ids = set()
    for event in today_events:
        item = event.item
        if item.source != Sources.TMDB.value:
            continue
        if item.media_type == MediaTypes.MOVIE.value:
            movie_media_ids.add(item.media_id)
        elif item.media_type == MediaTypes.SEASON.value:
            tv_media_ids.add(item.media_id)

    active_statuses = [Status.IN_PROGRESS.value, Status.PLANNING.value]
    candidates = []
    for media_type, media_ids in (
        (MediaTypes.MOVIE.value, movie_media_ids),
        (MediaTypes.TV.value, tv_media_ids),
    ):
        if not media_ids:
            continue
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        qs = model.objects.filter(
            user=user,
            status__in=active_statuses,
            item__source=Sources.TMDB.value,
            item__media_id__in=media_ids,
        ).select_related("item")
        candidates.extend((media_type, media) for media in qs)
    return candidates


def _available_providers_in_region(meta, region):
    """Return the set of TMDB provider IDs streaming this item in ``region``.

    Pulls flatrate + free buckets; ignores rent / buy / ads (matches the
    media_details chip filter). Returns an empty set when the metadata
    or region key is missing.
    """
    region_data = (meta.get("providers") or {}).get(region) or {}
    return {
        p.get("provider_id")
        for p in (region_data.get("flatrate") or []) + (region_data.get("free") or [])
    }


def _merge_watch_tonight_candidates(today_candidates, recent_candidates):
    """Merge release-today and recent-Planning candidates, deduped by media pk."""
    candidates = []
    seen = set()
    for mt, media in (*today_candidates, *recent_candidates):
        key = (mt, media.pk)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((mt, media))
    return candidates


def _watch_tonight(user, *, limit=_WATCH_TONIGHT_LIMIT):
    """Top In progress / Planning Movies / TV streaming on a user's services.

    Returns a list of ``{"media", "item", "match_score", "providers",
    "releases_today"}`` dicts. Items with a release event today (new
    episode airing or movie hitting streaming) are sorted to the front
    so the user does not miss a same-day drop; everything else falls
    back to best taste-match, then most recently added. Empty when the
    user has set no streaming services, has no region selected, or no
    candidate items have cached metadata yet.

    Cold-cache behavior: we **never** trigger a TMDB fetch from here —
    we read metadata via ``cache.get_many`` only. Titles the user has
    viewed are cached for 24h, so the rail fills in organically as the
    user browses their library. This keeps the home page request bounded
    to a single Redis round-trip regardless of candidate-list size.
    """
    subscribed = config.parse_streaming_providers(user.streaming_providers)
    region = user.watch_provider_region or ""
    if not subscribed or region in ("", "UNSET"):
        return []

    # Items with a release today (In progress + Planning) go to the front;
    # recent Planning items fill in the rest of the rail.
    today_candidates = _releases_today_candidates(user)
    today_keys = {(mt, media.pk) for mt, media in today_candidates}
    recent_candidates = _recent_planning_candidates(
        user,
        cap=_WATCH_TONIGHT_CANDIDATE_CAP,
    )
    candidates = _merge_watch_tonight_candidates(today_candidates, recent_candidates)
    if not candidates:
        return []

    cache_keys = [
        f"{Sources.TMDB.value}_{mt}_{media.item.media_id}" for mt, media in candidates
    ]
    cached = cache.get_many(cache_keys)
    if not cached:
        return []

    # Build taste profiles lazily — one per media_type — and only when
    # the user has enough signal. Otherwise we still rank by recency.
    profiles = {}
    for mt in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        profile = taste.build_profile(user, mt)
        if taste.has_enough_signal(profile):
            profiles[mt] = profile

    provider_lookup = {
        entry["id"]: entry["name"] for entry in config.STREAMING_PROVIDERS
    }

    results = []
    for (media_type, media), key in zip(candidates, cache_keys, strict=True):
        meta = cached.get(key)
        if not meta:
            continue
        matches = subscribed & _available_providers_in_region(meta, region)
        if not matches:
            continue
        profile = profiles.get(media_type)
        match_score = (
            taste.score_item(profile, meta.get("genres") or []) if profile else None
        )
        results.append(
            {
                "media": media,
                "item": media.item,
                "media_type": media_type,
                "match_score": match_score,
                "releases_today": (media_type, media.pk) in today_keys,
                "providers": [
                    {"id": pid, "name": provider_lookup.get(pid, "")} for pid in matches
                ],
            },
        )

    # Releases today first, then best match, then most-recently-added.
    results.sort(
        key=lambda r: (
            not r["releases_today"],
            -(r["match_score"] or 0),
            -r["media"].created_at.timestamp(),
        ),
    )
    return results[:limit]


def _stale_planning(user, *, limit=5, days=180):
    """Planning-status items that have been sitting around for more than `days`.

    Sorted oldest-first so the nudge surfaces what the user has neglected
    the longest. Limited; this is a re-engagement hint, not a backlog view.
    """
    threshold = timezone.now() - timedelta(days=days)
    candidates = []
    for media_type in MediaTypes.values:
        if media_type == MediaTypes.EPISODE.value:
            continue
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        field_names = {f.name for f in model._meta.fields}
        if "status" not in field_names or "created_at" not in field_names:
            continue
        qs = (
            model.objects.filter(
                user=user,
                status=Status.PLANNING.value,
                created_at__lt=threshold,
            )
            .select_related("item")
            .order_by("created_at")[: limit * 2]
        )
        candidates.extend(
            {
                "item": media.item,
                "since": media.created_at,
                "media_type": media_type,
            }
            for media in qs
        )

    candidates.sort(key=lambda c: c["since"])
    return candidates[:limit]


def _recent_activity(user, *, limit=8):
    """Recent simple_history rows across every tracked media type.

    Scans each HistoricalRecord table for the user's last `limit` rows,
    over-fetches to allow for deleted media, then hydrates the surviving rows
    with their live Item (poster + title). Skips deletes — they're rare and
    showing them without the item info is noisy.

    Cheap enough to run on every home render for a single-user homelab; if it
    shows up in a profile we can cache it per-user with a short TTL.
    """
    rows = []
    common_fields = ("id", "history_type", "history_date")
    for name in BasicMedia.objects.get_historical_models():
        # Episode rows are noise at the home-rail level (one per tick) and the
        # live `episode` model has no `user` field for the hydration filter
        # below -- its user lives on related_season.user. Season/TV activity
        # already covers the show-level signal.
        if name == "historicalepisode":
            continue
        model = apps.get_model("app", name)
        # `status` is on most but not all subclasses, so probe per-model and
        # skip the field when absent.
        field_names = {f.name for f in model._meta.fields}
        fields = common_fields + (("status",) if "status" in field_names else ())
        recent = (
            model.objects.filter(history_user_id=user.id)
            .order_by("-history_date")
            .values(*fields)[:limit]
        )
        live_model_name = name.replace("historical", "")
        for r in recent:
            r.setdefault("status", None)
            r["live_model_name"] = live_model_name
            rows.append(r)

    rows.sort(key=lambda r: r["history_date"], reverse=True)
    rows = rows[: limit * 3]  # over-fetch; some media may be gone

    result = []
    for r in rows:
        if r["history_type"] == "-":
            continue
        try:
            live_model = apps.get_model("app", r["live_model_name"])
            media = (
                live_model.objects.select_related("item")
                .filter(id=r["id"], user_id=user.id)
                .first()
            )
        except LookupError:
            continue
        if not media:
            continue
        r["item"] = media.item
        result.append(r)
        if len(result) >= limit:
            break
    return result


@require_POST
def progress_edit(request, media_type, instance_id):
    """Increase or decrease the progress of a media item from home page."""
    operation = request.POST["operation"]

    media = BasicMedia.objects.get_media_prefetch(
        request.user,
        media_type,
        instance_id,
    )

    if operation == "increase":
        media.increase_progress()
    elif operation == "decrease":
        media.decrease_progress()

    if media_type == MediaTypes.SEASON.value:
        # clear prefetch cache to get the updated episodes
        media.refresh_from_db()
        prefetch_related_objects([media], "episodes")

    context = {
        "media": media,
    }
    return render(
        request,
        "app/components/progress_changer.html",
        context,
    )


@require_GET
def media_list(request, media_type):
    """Return the media list page."""
    layout = request.user.update_preference(
        f"{media_type}_layout",
        request.GET.get("layout"),
    )
    sort_filter = request.user.update_preference(
        f"{media_type}_sort",
        request.GET.get("sort"),
    )
    status_filter = request.user.update_preference(
        f"{media_type}_status",
        request.GET.get("status"),
    )
    search_query = request.GET.get("search", "")
    mood_filter = request.GET.get("mood", "").strip() or None
    page = request.GET.get("page", 1)

    # Prepare status filter for database query
    if not status_filter:
        status_filter = MediaStatusChoices.ALL

    # Get media list with filters applied
    media_queryset = BasicMedia.objects.get_media_list(
        user=request.user,
        media_type=media_type,
        status_filter=status_filter,
        sort_filter=sort_filter,
        search=search_query,
        mood=mood_filter,
    )

    # Paginate results
    items_per_page = 32
    paginator = Paginator(media_queryset, items_per_page)
    media_page = paginator.get_page(page)

    BasicMedia.objects.annotate_max_progress(
        media_page.object_list,
        media_type,
    )

    # Records have a binary owned/wanted model — narrow the status filter to
    # just those two options (relabeled) plus All. Other media types keep the
    # full set.
    if media_type == MediaTypes.RECORD.value:
        status_choices = [
            (MediaStatusChoices.ALL.value, "All"),
            (Status.COMPLETED.value, "Owned"),
            (Status.PLANNING.value, "Want"),
        ]
    else:
        status_choices = MediaStatusChoices.choices

    context = {
        "media_type": media_type,
        "media_type_plural": app_tags.media_type_readable_plural(media_type).lower(),
        "media_list": media_page,
        "current_layout": layout,
        "layout_class": ".media-grid" if layout == "grid" else "tbody",
        "current_sort": sort_filter,
        "current_status": status_filter,
        "sort_choices": MediaSortChoices.choices,
        "status_choices": status_choices,
        "current_mood": mood_filter or "",
        "mood_choices": MOOD_LABELS,
    }

    # Per-media-type stats panel. Only records have one today; the contract is
    # the view returns ``None`` for "no panel" so the template can skip cleanly.
    if media_type == MediaTypes.RECORD.value and not request.headers.get(
        "HX-Request",
    ):
        context["record_stats"] = stats.get_record_stats(request.user)

    # Games carry real runtime in their progress field (minutes played),
    # so the games list gets a playtime panel.
    if media_type == MediaTypes.GAME.value and not request.headers.get(
        "HX-Request",
    ):
        context["game_stats"] = stats.get_game_stats(request.user)

    # Handle HTMX requests for partial updates
    if request.headers.get("HX-Request"):
        # Filtering from empty list
        if request.headers.get("HX-Target") == "empty_list":
            # If still empty, keep user in the same page
            if not media_page.object_list:
                return HttpResponse(status=204)
            response = HttpResponse()
            response["HX-Redirect"] = reverse("medialist", args=[media_type])
            return response
        if layout == "grid":
            template_name = "app/components/media_grid_items.html"
        else:
            template_name = "app/components/media_table_items.html"
    else:
        template_name = "app/media_list.html"

    return render(request, template_name, context)


@require_GET
def media_search(request):
    """Return the media search page."""
    media_type = request.user.update_preference(
        "last_search_type",
        request.GET["media_type"],
    )
    query = request.GET["q"]
    page = int(request.GET.get("page", 1))
    layout = request.GET.get("layout", "grid")

    # only receives source when searching with secondary source
    source = request.GET.get(
        "source",
        config.get_default_source_name(media_type).value,
    )

    data = services.search(media_type, query, page, source)

    # Enrich search results with user tracking data
    if data.get("results"):
        data["results"] = helpers.enrich_items_with_user_data(
            request, data["results"], "search"
        )

    # For Discogs record searches, surface matching artists at the top so
    # users can browse a discography without first having to add one of
    # the artist's records. Capped to 6 hits to keep the strip compact;
    # only shown on page 1 since paging is per-result-type.
    artist_matches = []
    if (
        media_type == MediaTypes.RECORD.value
        and source == Sources.DISCOGS.value
        and page == 1
    ):
        try:
            artist_matches = discogs.artist_search(query, limit=6)
        except services.ProviderAPIError:
            artist_matches = []

    context = {
        "data": data,
        "source": source,
        "media_type": media_type,
        "layout": layout,
        "artist_matches": artist_matches,
    }

    return render(request, "app/search.html", context)


BROWSE_SOURCES = (
    {"value": Sources.TMDB.value, "label": "TMDB", "module": tmdb},
    {"value": "trakt", "label": "Trakt", "module": trakt},
)


def _available_browse_sources():
    """Return the browse sources that have valid credentials configured."""
    return [
        source
        for source in BROWSE_SOURCES
        if source["value"] == Sources.TMDB.value or trakt.is_configured()
    ]


@require_GET
def browse(request):
    """Browse curated movie / TV lists from one of several providers."""
    media_type = request.GET.get("media_type", MediaTypes.MOVIE.value)
    if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        media_type = MediaTypes.MOVIE.value

    available_sources = _available_browse_sources()
    source_lookup = {entry["value"]: entry for entry in available_sources}
    source = request.GET.get("source", Sources.TMDB.value)
    if source not in source_lookup:
        source = Sources.TMDB.value
    provider = source_lookup[source]["module"]

    categories = provider.browse_categories(media_type)
    valid_categories = {category["value"] for category in categories}
    category = request.GET.get("category", categories[0]["value"])
    if category not in valid_categories:
        category = categories[0]["value"]

    page = int(request.GET.get("page", 1))
    layout = request.GET.get("layout", "grid")

    # Genre filter — TMDB only (Trakt slugs and TMDB ids don't share a
    # vocabulary, so we just hide the filter for Trakt). Silently drops
    # stale ids so a bookmarked URL never errors.
    if source == Sources.TMDB.value:
        selected_genre_ids, available_genres = _resolve_browse_genres(
            media_type,
            request.GET.get("genres", ""),
        )
    else:
        selected_genre_ids, available_genres = [], []
    genres_csv = ",".join(str(g) for g in selected_genre_ids)

    if source == Sources.TMDB.value:
        provider_kwargs = {"genres": selected_genre_ids} if selected_genre_ids else {}
        if category == "for_you":
            data = provider.for_you_browse(
                media_type,
                request.user,
                page,
                request.user.watch_provider_region,
                **provider_kwargs,
            )
        else:
            data = provider.browse(
                media_type,
                category,
                page,
                request.user.watch_provider_region,
                **provider_kwargs,
            )
    else:
        data = provider.browse(media_type, category, page)

    if data.get("results"):
        # Drop tiles the user previously marked 'not interested' so they
        # don't keep cluttering the discovery rows. Filter before
        # enrichment so we don't waste a DB query annotating items we're
        # about to throw away. (for_you_browse already filters its own
        # candidate pool against dismissals + library; the redundant
        # filter here is a no-op for that category.)
        dismissed_ids = set(
            DismissedItem.objects.filter(
                user=request.user,
                source=source,
                media_type=media_type,
            ).values_list("media_id", flat=True),
        )
        if dismissed_ids:
            data["results"] = [
                r
                for r in data["results"]
                if str(r.get("media_id")) not in dismissed_ids
            ]
        # Default language filter — Hindi-language titles dominate
        # TMDB's "popular" / "trending" lists in some regions despite
        # being effectively unwatchable for English-only users, so
        # we drop them by default. Everything else passes through.
        # Toggleable; TMDB-only since other sources don't populate
        # original_language consistently.
        if source == Sources.TMDB.value and not request.user.browse_include_non_english:
            blocked_languages = {"hi"}
            data["results"] = [
                r
                for r in data["results"]
                if (r.get("original_language") or "") not in blocked_languages
            ]
        # Annotate with personal match scores so the % badge can render.
        # No-op on cold-start / unsupported sources.
        data["results"] = taste.attach_match_scores(
            request.user,
            media_type,
            source,
            data["results"],
        )
        data["results"] = helpers.enrich_items_with_user_data(
            request, data["results"], "browse"
        )

    context = {
        "data": data,
        "media_type": media_type,
        "category": category,
        "categories": categories,
        "layout": layout,
        "source": source,
        "show_dismiss": True,
        "sources": [
            {"value": entry["value"], "label": entry["label"]}
            for entry in available_sources
        ],
        "available_genres": available_genres,
        "genres_csv": genres_csv,
    }
    return render(request, "app/browse.html", context)


def _toggle_genre_csv(current_ids, gid):
    """Return the comma-separated genre id string after toggling ``gid``.

    ``current_ids`` is the list of already-selected genre ids, in the
    order they appeared in the URL. Adds or removes ``gid`` while
    preserving order so the chip row doesn't visibly re-shuffle.
    """
    if gid in current_ids:
        next_ids = [g for g in current_ids if g != gid]
    else:
        next_ids = [*current_ids, gid]
    return ",".join(str(g) for g in next_ids)


def _resolve_browse_genres(media_type, raw):
    """Parse `?genres=` and pair it with the available-genre list.

    Returns ``(selected_ids, available)`` where ``selected_ids`` is the
    validated list of genre ids preserved in URL order, and
    ``available`` is the chip-row payload (id, name, active flag, and
    the CSV that toggling this chip would produce). Unknown ids and
    non-numeric junk are dropped so a stale bookmark never errors.
    """
    genre_map = tmdb.get_genre_map(media_type)
    selected_ids = []
    for raw_chunk in raw.split(","):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        try:
            gid = int(chunk)
        except ValueError:
            continue
        if gid in genre_map and gid not in selected_ids:
            selected_ids.append(gid)
    selected_set = set(selected_ids)
    available = [
        {
            "id": gid,
            "name": name,
            "active": gid in selected_set,
            "toggle": _toggle_genre_csv(selected_ids, gid),
        }
        for gid, name in sorted(genre_map.items(), key=lambda kv: kv[1])
    ]
    return selected_ids, available


def _reading_projection(sessions, current_percentage, book):
    """Estimate reading pace and a projected finish date for a book.

    Uses the span from the user's first recorded KOReader session to the
    latest synced position: average forward pace over that window, then
    extrapolate the remaining fraction to a finish date. Returns ``None``
    unless the book is in progress with enough signal to be meaningful —
    a multi-day span, real forward progress, and a position that's
    started but not effectively done. ``sessions`` is newest-first (so
    the oldest, the baseline, is last). Pace is also expressed in
    pages/day when the page count can be inferred from the current page
    progress and percentage.
    """
    if book.status != Status.IN_PROGRESS.value or current_percentage is None:
        return None

    current_fraction = current_percentage / 100
    completion_floor = 0.97
    if not 0 < current_fraction < completion_floor:
        return None
    if not sessions:
        return None

    oldest = sessions[-1]
    elapsed_days = (timezone.now() - oldest.start).total_seconds() / 86400
    gained = current_fraction - oldest.percent_start
    # Need a real multi-day window and forward motion, or the
    # extrapolation is noise (e.g. one burst of reading on day one).
    if elapsed_days < 1 or gained <= 0:
        return None

    pace_per_day = gained / elapsed_days
    days_left = (1.0 - current_fraction) / pace_per_day
    # A projection further out than a couple of years is not useful and
    # usually means the pace sample is too small; don't show it.
    max_projection_days = 730
    if days_left > max_projection_days:
        return None

    projection = {
        "days_left": round(days_left),
        "projected_finish": timezone.now() + timedelta(days=days_left),
        "pace_pct_per_day": round(pace_per_day * 100, 1),
    }
    if book.progress:
        total_pages = book.progress / current_fraction
        projection["pace_pages_per_day"] = round(total_pages * pace_per_day)
    return projection


def _koreader_book_summary(user, book):
    """Return KOReader reading-history data for ``book`` or ``None``.

    Pulls everything the book detail page needs to render both the
    right-rail summary chip and the full inline reading-history section
    (stats grid, journey chart payload, full session list). Returns
    ``None`` when the user has no KOReader mappings for the book, or
    has mappings but no events yet. Imports the stats helper lazily so
    the media_details path doesn't pay the import cost for non-book
    requests.
    """
    from integrations.koreader_stats import (  # noqa: PLC0415
        aggregate_reading_time,
        compute_sessions,
    )

    koreader_event_model = apps.get_model("integrations", "KOReaderProgressEvent")
    koreader_mapping_model = apps.get_model("integrations", "KOReaderBookMapping")

    mappings = list(
        koreader_mapping_model.objects.filter(user=user, item=book.item),
    )
    if not mappings:
        return None

    events_qs = koreader_event_model.objects.filter(
        user=user,
        mapping__in=mappings,
    )
    event_count = events_qs.count()
    if not event_count:
        return None

    # Single-mapping common case: filter at the query layer. Rare
    # multi-mapping case (multiple epub editions for the same book):
    # post-filter the per-user session list, since the session helper
    # splits on mapping change and we want sessions for any of the
    # book's mappings.
    if len(mappings) == 1:
        all_sessions = compute_sessions(user, mapping=mappings[0])
    else:
        mapping_ids = {m.id for m in mappings}
        all_sessions = [
            s for s in compute_sessions(user) if s.mapping_id in mapping_ids
        ]
    total_minutes, _session_count, _avg = aggregate_reading_time(all_sessions)

    latest_mapping = max(
        (m for m in mappings if m.last_progress_at is not None),
        key=lambda m: m.last_progress_at,
        default=mappings[0],
    )

    # Distinct device count (matches the standalone view's tally:
    # device_id wins when present, otherwise device name, otherwise
    # the literal "unknown" bucket).
    device_count = len(
        {
            (device_id or device_name or "unknown")
            for device_id, device_name in events_qs.values_list(
                "device_id",
                "device",
            ).distinct()
        },
    )

    # Latest sync percentage. ``book.progress`` is page count, not a
    # percentage — use the actual 0.0-1.0 fraction KOReader pushed.
    last_event = events_qs.order_by("-created_at").values("percentage").first()
    if last_event is not None:
        current_percentage = round(last_event["percentage"] * 100, 1)
    elif latest_mapping.last_progress_at is not None:
        current_percentage = round(latest_mapping.last_percentage * 100, 1)
    else:
        current_percentage = None

    # Sessions come back newest-first; the chart wants oldest-first so
    # the bars read left-to-right chronologically. Pass the list to the
    # template as a plain Python list — ``{% ...|json_script %}`` will
    # encode it once. Pre-encoding with ``json.dumps`` here would make
    # the script tag contain a quoted JSON string literal, so
    # ``JSON.parse`` in the chart JS returns a string and the chart
    # silently bails on "payload is not an array".
    journey_data = [
        {
            "label": s.start.strftime("%b %-d"),
            "started": s.start.isoformat(),
            "ended": s.end.isoformat(),
            "duration_min": s.duration_minutes,
            "start_pct": round(s.percent_start * 100, 1),
            "end_pct": round(s.percent_end * 100, 1),
            "delta_pct": round(s.percent_traversed_pct, 1),
        }
        for s in reversed(all_sessions)
    ]

    return {
        "mapping": latest_mapping,
        "sessions": all_sessions[:3],
        "all_sessions": all_sessions,
        "event_count": event_count,
        "device_count": device_count,
        "current_percentage": current_percentage,
        "total_minutes": total_minutes,
        "total_hours": total_minutes / 60,
        "journey_data": journey_data,
        "projection": _reading_projection(all_sessions, current_percentage, book),
    }


@require_GET
def media_details(request, source, media_type, media_id, title):  # noqa: ARG001, C901, PLR0912 title for URL; complexity is acceptable here
    """Return the details page for a media item."""
    media_metadata = services.get_media_metadata(media_type, media_id, source)
    user_medias = BasicMedia.objects.filter_media_prefetch(
        request.user,
        media_id,
        media_type,
        source,
    )
    current_instance = user_medias[0] if user_medias else None

    # Enrich related items with user tracking data
    if media_metadata.get("related"):
        for section_name, related_items in media_metadata["related"].items():
            if related_items:
                media_metadata["related"][section_name] = (
                    helpers.enrich_items_with_user_data(
                        request, related_items, section_name
                    )
                )

    if media_type in ["tv", "movie"]:
        watch_providers = tmdb.filter_providers(
            media_metadata.get("providers"), request.user.watch_provider_region
        )
    else:
        watch_providers = None

    # Subscribed-provider IDs so the template can highlight chips that
    # the user actually has a sub for. Computed once here, passed in as
    # a set for cheap ``in`` checks in the loop.
    subscribed_provider_ids = config.parse_streaming_providers(
        request.user.streaming_providers,
    )

    context = {
        "media": media_metadata,
        "media_type": media_type,
        "user_medias": user_medias,
        "current_instance": current_instance,
        "watch_providers": watch_providers,
        "watch_provider_region": request.user.watch_provider_region,
        "subscribed_provider_ids": subscribed_provider_ids,
        "comparable_items": _comparable_items(
            request.user,
            media_type,
            current_instance,
        ),
    }

    # Books: surface a compact KOReader summary card on the book
    # detail page when the user has at least one sync event for this
    # book. Pulled into ``_koreader_book_summary`` to keep
    # ``media_details``' branch count under the ruff cap.
    if media_type == MediaTypes.BOOK.value and current_instance is not None:
        summary = _koreader_book_summary(request.user, current_instance)
        if summary is not None:
            context["koreader_history_book_pk"] = current_instance.pk
            context["koreader_summary"] = summary
        # Hardcover push status — small chip below the KOReader summary
        # so the user can tell at a glance whether this book is also
        # being mirrored to hardcover.app. Only loaded when the user
        # has actually connected an integration, so unauthenticated
        # users / non-Hardcover users see nothing extra.
        from integrations.models import HardcoverIntegration  # noqa: PLC0415

        hc = HardcoverIntegration.objects.filter(user=request.user).first()
        if hc is not None and hc.enabled:
            context["hardcover_status"] = {
                "username": hc.hardcover_username,
                "last_pushed_at": hc.last_pushed_at,
                "last_error": hc.last_error,
                "last_error_at": hc.last_error_at,
            }
    # Last-spin indicator on the Record detail page (only meaningful for records).
    if media_type == MediaTypes.RECORD.value:
        spin_qs = Play.objects.filter(
            user=request.user,
            item__media_id=media_id,
            item__source=source,
            item__media_type=MediaTypes.RECORD.value,
        )
        context["record_spin"] = spin_qs.order_by("-played_at").first()
        context["record_spin_count"] = spin_qs.count()

        # Koito-style listening stats panels: aggregate play history into
        # totals, top tracks, recent plays, and an activity heatmap.
        record_item = Item.objects.filter(
            media_id=media_id,
            source=source,
            media_type=MediaTypes.RECORD.value,
        ).first()
        if record_item:
            context["record_listen_stats"] = stats.get_record_listen_stats(
                record_item,
                request.user,
            )

        # Sides offered by the spin logger come from the actual tracklist
        # (Discogs releases past LPs as A/B/C/D… up to box sets). Fall back
        # to A/B so 7"s and untracked records still show useful buttons.
        context["record_spin_sides"] = _record_side_choices(record_item)

        # "More by this artist" — full Discogs discography of the credited
        # artist, with the current release filtered out and the user's
        # library overlaid so owned albums get an Owned badge. Soft-fails
        # to None on any Discogs error so the page still renders.
        # Prefer the Discogs artist ID embedded in the release metadata
        # over a name-based lookup: artists with disambiguation suffixes
        # like "Beyoncé (2)" trip the fuzzy search, but the release
        # already tells us the exact ID.
        primary_artist_info = _primary_artist_info(media_metadata)
        if primary_artist_info:
            primary_artist = primary_artist_info["name"]
            try:
                artist_id = primary_artist_info.get("id") or discogs.artist_lookup(
                    primary_artist,
                )
                if artist_id:
                    full_disco = discogs.artist_discography(artist_id)
                    other = [r for r in full_disco if r["media_id"] != media_id]
                    other_ids = {r["media_id"] for r in other}
                    owned = {
                        rec.item.media_id: rec
                        for rec in Record.objects.filter(
                            user=request.user,
                            item__source=Sources.DISCOGS.value,
                            item__media_type=MediaTypes.RECORD.value,
                            item__media_id__in=other_ids,
                        ).select_related("item")
                    }
                    context["artist_discography"] = [
                        {"release": r, "media": owned.get(r["media_id"])} for r in other
                    ]
                    context["artist_discography_name"] = primary_artist
                    context["artist_discography_owned"] = sum(
                        1 for r in context["artist_discography"] if r["media"]
                    )
            except services.ProviderAPIError:
                logger.warning(
                    "Discogs discography lookup failed for %r",
                    primary_artist,
                )
    return render(request, "app/media_details.html", context)


def _primary_artist_info(media_metadata):
    """Return ``{"id", "name"}`` for the first credited artist.

    Prefers the structured ``artists`` list from the Discogs release
    response (each entry carries the canonical artist ID). Falls back to
    parsing the joined ``details.artist`` string when the structured
    list is missing — e.g., cached responses from before this field
    existed, or non-Discogs sources.
    """
    artists = media_metadata.get("artists") or []
    if artists:
        first = artists[0]
        if first.get("name"):
            return {"id": first.get("id"), "name": first["name"]}

    joined = (media_metadata.get("details") or {}).get("artist") or ""
    if not joined:
        return None
    name = joined.split(",", 1)[0].strip()
    return {"id": None, "name": name} if name else None


def _comparable_items(user, media_type, current_instance, *, limit=5):
    """Items the user rated within ±1 of the current item, same media_type.

    Surfaces a "you might compare it to…" rail on the detail page. Returns
    an empty list if the user hasn't rated the current item yet (no anchor
    for the comparison) or if the media model has no ``score`` field.
    """
    if current_instance is None:
        return []
    score = getattr(current_instance, "score", None)
    if score is None:
        return []
    try:
        model = apps.get_model("app", media_type)
    except LookupError:
        return []
    field_names = {f.name for f in model._meta.fields}
    if "score" not in field_names:
        return []
    qs = (
        model.objects.filter(
            user=user,
            score__gte=max(0, float(score) - 1),
            score__lte=min(10, float(score) + 1),
        )
        .exclude(pk=current_instance.pk)
        .select_related("item")
        .order_by("-score", "-created_at")[: limit * 2]
    )
    # Dedup by item — multiple Media rows can exist for repeat plays.
    seen = set()
    out = []
    for media in qs:
        if media.item_id in seen:
            continue
        seen.add(media.item_id)
        out.append({"item": media.item, "score": media.score})
        if len(out) >= limit:
            break
    return out


def _record_side_choices(record_item):
    """Return ordered list of unique side letters for a record."""
    sides = []
    if record_item is not None:
        # Lazily populate Tracks from Discogs on first view so box sets show
        # their real sides (C/D/E/F/…) instead of defaulting to A/B.
        tracks = ensure_record_tracks(record_item)
        seen = set()
        for track in tracks:
            if track.side and track.side not in seen:
                seen.add(track.side)
                sides.append(track.side)
    if not sides:
        sides = ["A", "B"]
    return sorted(sides)


PERSON_SORT_CHOICES = (
    ("date_desc", "Newest"),
    ("date_asc", "Oldest"),
    ("popularity", "Popularity"),
    ("title", "Title"),
)

PERSON_TYPE_CHOICES = (
    ("all", "All"),
    (MediaTypes.MOVIE.value, "Movies"),
    (MediaTypes.TV.value, "TV Shows"),
)

PERSON_ROLE_CHOICES = (
    ("acting", "Acting"),
    ("crew", "Crew"),
    ("all", "All"),
)


def _sort_person_credits(entries, sort_by):
    """Return person credits sorted according to the requested key."""
    if sort_by == "date_asc":
        return sorted(
            entries,
            key=lambda c: (c.get("release_date") or "9999-99-99", c["title"].lower()),
        )
    if sort_by == "popularity":
        return sorted(
            entries,
            key=lambda c: (-(c.get("popularity") or 0), c["title"].lower()),
        )
    if sort_by == "title":
        return sorted(entries, key=lambda c: c["title"].lower())
    return sorted(
        entries,
        key=lambda c: (c.get("release_date") or "", c["title"].lower()),
        reverse=True,
    )


def _select_person_credits(person_metadata, role_filter, type_filter):
    """Return person credits matching the role and type filters."""
    if role_filter == "acting":
        entries = list(person_metadata["cast_credits"])
    elif role_filter == "crew":
        entries = list(person_metadata["crew_credits"])
    else:
        entries = list(person_metadata["cast_credits"]) + list(
            person_metadata["crew_credits"]
        )

    if type_filter != "all":
        entries = [c for c in entries if c["media_type"] == type_filter]

    return entries


@require_GET
def person_details(request, person_id, name):  # noqa: ARG001 name for URL
    """Render the filmography page for a TMDB person."""
    person_metadata = tmdb.person(person_id)

    sort_by = request.GET.get("sort", "date_desc")
    if sort_by not in {key for key, _ in PERSON_SORT_CHOICES}:
        sort_by = "date_desc"

    type_filter = request.GET.get("type", "all")
    if type_filter not in {key for key, _ in PERSON_TYPE_CHOICES}:
        type_filter = "all"

    role_filter = request.GET.get("role", "acting")
    if role_filter not in {key for key, _ in PERSON_ROLE_CHOICES}:
        role_filter = "acting"

    entries = _select_person_credits(person_metadata, role_filter, type_filter)
    entries = _sort_person_credits(entries, sort_by)

    # enrich_items_with_user_data needs a homogeneous media_type per call,
    # so split by media type and stitch the per-credit user data back on.
    by_type = {}
    for credit in entries:
        by_type.setdefault(credit["media_type"], []).append(credit)

    user_media_by_key = {}
    for media_type, items in by_type.items():
        enriched = helpers.enrich_items_with_user_data(request, items, "filmography")
        for entry in enriched:
            key = (media_type, str(entry["item"]["media_id"]))
            user_media_by_key[key] = entry["media"]

    results = [
        {
            "item": credit,
            "media": user_media_by_key.get(
                (credit["media_type"], str(credit["media_id"])),
            ),
        }
        for credit in entries
    ]

    # Aggregate "your stats with this person": tracked count, avg score,
    # high-rating count. Skips silently when the user has no overlap with
    # this person's filmography. ``r["media"]`` is a Django Model instance
    # (see enrich_items_with_user_data), so score is an attribute, not a
    # mapping key — using getattr keeps Episode (no score field) safe.
    tracked = [r for r in results if r["media"] is not None]
    rated = [
        score
        for score in (getattr(r["media"], "score", None) for r in tracked)
        if score is not None
    ]
    person_stats = None
    if tracked:
        person_stats = {
            "tracked_count": len(tracked),
            "rated_count": len(rated),
            "avg_score": round(sum(rated) / len(rated), 1) if rated else None,
            "high_rating_count": sum(1 for s in rated if s >= _HIGH_SCORE_THRESHOLD),
        }

    context = {
        "person": person_metadata,
        "results": results,
        "total_count": len(results),
        "sort_by": sort_by,
        "sort_choices": PERSON_SORT_CHOICES,
        "type_filter": type_filter,
        "type_choices": PERSON_TYPE_CHOICES,
        "role_filter": role_filter,
        "role_choices": PERSON_ROLE_CHOICES,
        "person_stats": person_stats,
    }
    return render(request, "app/person.html", context)


ARTIST_DISCO_FILTERS = (
    ("all", "All"),
    ("owned", "In your library"),
    ("missing", "Not in your library"),
)

ARTIST_DISCO_SORTS = (
    ("year_desc", "Newest"),
    ("year_asc", "Oldest"),
    ("title", "Title"),
)


def _sort_annotated_releases(annotated, sort_by):
    """Sort the annotated artist-discography list in place by ``sort_by``."""
    if sort_by == "year_asc":
        annotated.sort(
            key=lambda r: (
                r["release"]["year"] or 9999,
                (r["release"]["title"] or "").lower(),
            ),
        )
    elif sort_by == "title":
        annotated.sort(key=lambda r: (r["release"]["title"] or "").lower())
    else:  # year_desc (default)
        annotated.sort(
            key=lambda r: (
                -(r["release"]["year"] or 0),
                (r["release"]["title"] or "").lower(),
            ),
        )


@require_GET
def artist_details(request, name):
    """Render the Discogs artist page with their full discography.

    Each release is annotated with the user's tracked Record (if any) so
    the template can flag owned entries and link them straight to the
    record detail page.
    """
    artist_id = discogs.artist_lookup(name)
    if not artist_id:
        return render(
            request,
            "app/artist.html",
            {
                "artist": {"name": name, "image": settings.IMG_NONE},
                "artist_not_found": True,
                "releases": [],
                "total_count": 0,
                "owned_count": 0,
                "filter_choices": ARTIST_DISCO_FILTERS,
                "sort_choices": ARTIST_DISCO_SORTS,
                "filter_by": "all",
                "sort_by": "year_desc",
            },
            status=404,
        )

    artist_metadata = discogs.artist(artist_id)
    releases = discogs.artist_discography(artist_id)

    # Map every release media_id to the user's Record (if tracked) so the
    # grid can show an "Owned" badge and link straight to the existing
    # detail page without a second per-card query.
    release_ids = {r["media_id"] for r in releases}
    user_records = {
        rec.item.media_id: rec
        for rec in Record.objects.filter(
            user=request.user,
            item__source=Sources.DISCOGS.value,
            item__media_type=MediaTypes.RECORD.value,
            item__media_id__in=release_ids,
        ).select_related("item")
    }

    annotated = []
    for release in releases:
        media = user_records.get(release["media_id"])
        annotated.append({"release": release, "media": media})

    filter_by = request.GET.get("filter", "all")
    if filter_by not in {key for key, _ in ARTIST_DISCO_FILTERS}:
        filter_by = "all"
    if filter_by == "owned":
        annotated = [r for r in annotated if r["media"] is not None]
    elif filter_by == "missing":
        annotated = [r for r in annotated if r["media"] is None]

    sort_by = request.GET.get("sort", "year_desc")
    if sort_by not in {key for key, _ in ARTIST_DISCO_SORTS}:
        sort_by = "year_desc"
    _sort_annotated_releases(annotated, sort_by)

    # owned_count reflects the unfiltered library overlap so the header
    # number stays stable while the user toggles filters.
    owned_count = len(user_records)

    context = {
        "artist": artist_metadata,
        "releases": annotated,
        "total_count": len(releases),
        "owned_count": owned_count,
        "shown_count": len(annotated),
        "filter_choices": ARTIST_DISCO_FILTERS,
        "sort_choices": ARTIST_DISCO_SORTS,
        "filter_by": filter_by,
        "sort_by": sort_by,
    }
    return render(request, "app/artist.html", context)


@require_GET
def season_details(request, source, media_id, title, season_number):  # noqa: ARG001 For URL
    """Return the details page for a season."""
    tv_with_seasons_metadata = services.get_media_metadata(
        "tv_with_seasons",
        media_id,
        source,
        [season_number],
    )
    season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]

    user_medias = BasicMedia.objects.filter_media_prefetch(
        request.user,
        media_id,
        MediaTypes.SEASON.value,
        source,
        season_number=season_number,
    )

    current_instance = user_medias[0] if user_medias else None
    episodes_in_db = current_instance.episodes.all() if current_instance else []

    if source == Sources.MANUAL.value:
        season_metadata["episodes"] = manual.process_episodes(
            season_metadata,
            episodes_in_db,
        )
    else:
        season_metadata["episodes"] = tmdb.process_episodes(
            season_metadata,
            episodes_in_db,
        )

    # Enrich related items with user tracking data
    if season_metadata.get("related"):
        for section_name, related_items in season_metadata["related"].items():
            if related_items:
                season_metadata["related"][section_name] = (
                    helpers.enrich_items_with_user_data(
                        request,
                        related_items,
                        section_name,
                    )
                )

    context = {
        "media": season_metadata,
        "tv": tv_with_seasons_metadata,
        "media_type": MediaTypes.SEASON.value,
        "user_medias": user_medias,
        "current_instance": current_instance,
        "watch_providers": tmdb.filter_providers(
            season_metadata.get("providers"), request.user.watch_provider_region
        ),
        "watch_provider_region": request.user.watch_provider_region,
        "subscribed_provider_ids": config.parse_streaming_providers(
            request.user.streaming_providers,
        ),
    }
    return render(request, "app/media_details.html", context)


@require_POST
def update_media_score(request, media_type, instance_id):
    """Update the user's score for a media item."""
    media = BasicMedia.objects.get_media(
        request.user,
        media_type,
        instance_id,
    )

    score = float(request.POST.get("score"))
    media.score = score
    media.save()
    logger.info(
        "%s score updated to %s",
        media,
        score,
    )

    return JsonResponse(
        {
            "success": True,
            "score": score,
        },
    )


@require_POST
def update_media_status(request, media_type, instance_id):
    """Update the status for an already-tracked media item.

    Powers the status-sheet popover on the detail page: a click on one of the
    five status pills (Completed / In progress / Planning / Paused / Dropped)
    POSTs here and the popover updates without leaving the page. Falls through
    to Media.save() so the existing process_status() hook still fires (progress
    bumps, end_date stamping, calendar refresh, simple_history audit row).
    """
    status = request.POST.get("status")
    valid = {s.value for s in Status}
    if status not in valid:
        return JsonResponse({"success": False, "error": "invalid status"}, status=400)

    media = BasicMedia.objects.get_media(request.user, media_type, instance_id)
    media.status = status
    media.save()
    logger.info("%s status updated to %s", media, status)
    return JsonResponse({"success": True, "status": status})


@require_POST
def sync_metadata(request, source, media_type, media_id, season_number=None):
    """Refresh the metadata for a media item."""
    if source == Sources.MANUAL.value:
        msg = "Manual items cannot be synced."
        messages.error(request, msg)
        return HttpResponse(
            msg,
            status=400,
            headers={"HX-Redirect": request.POST.get("next", "/")},
        )

    cache_key = f"{source}_{media_type}_{media_id}"
    if media_type == MediaTypes.SEASON.value:
        cache_key += f"_{season_number}"

    ttl = cache.ttl(cache_key)
    logger.debug("%s - Cache TTL for: %s", cache_key, ttl)

    if ttl is not None and ttl > (settings.CACHE_TIMEOUT - 3):
        msg = "The data was recently synced, please wait a few seconds."
        messages.error(request, msg)
        logger.error(msg)
    else:
        deleted = cache.delete(cache_key)
        logger.debug("%s - Old cache deleted: %s", cache_key, deleted)

        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
        )
        item, _ = Item.objects.update_or_create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            defaults={
                "title": metadata["title"],
                "image": metadata["image"],
            },
        )
        title = metadata["title"]
        if season_number:
            title += f" - Season {season_number}"

        if media_type == MediaTypes.SEASON.value:
            metadata["episodes"] = tmdb.process_episodes(
                metadata,
                [],
            )

            # Create a dictionary of existing episodes keyed by episode number
            existing_episodes = {
                ep.episode_number: ep
                for ep in Item.objects.filter(
                    source=source,
                    media_type=MediaTypes.EPISODE.value,
                    media_id=media_id,
                    season_number=season_number,
                )
            }

            episodes_to_update = []
            episode_count = 0

            for episode_data in metadata["episodes"]:
                episode_number = episode_data["episode_number"]
                if episode_number in existing_episodes:
                    episode_item = existing_episodes[episode_number]
                    episode_item.title = metadata["title"]
                    episode_item.image = episode_data["image"]
                    episodes_to_update.append(episode_item)
                    episode_count += 1

            logger.info(
                "Found %s existing episodes to update for %s",
                episode_count,
                title,
            )

            if episodes_to_update:
                updated_count = Item.objects.bulk_update(
                    episodes_to_update,
                    ["title", "image"],
                    batch_size=100,
                )
                logger.info(
                    "Successfully updated %s episodes for %s",
                    updated_count,
                    title,
                )

        item.fetch_releases(delay=False)

        msg = f"{title} was synced to {Sources(source).label} successfully."
        messages.success(request, msg)

    if request.headers.get("HX-Request"):
        return HttpResponse(
            status=204,
            headers={
                "HX-Redirect": request.POST["next"],
            },
        )
    return helpers.redirect_back(request)


def _fetch_book_total_pages(media_id, source):
    """Return total page count for a book, or None if unavailable.

    Wrapped in a swallow-everything except: never let a metadata fetch
    block the user from opening the track modal. Provider metadata is
    Redis-cached for 24h, so this is cheap on repeat opens.
    """
    try:
        metadata = services.get_media_metadata(MediaTypes.BOOK.value, media_id, source)
    except Exception:  # noqa: BLE001
        return None
    if not metadata:
        return None
    return metadata.get("max_progress") or (
        (metadata.get("details") or {}).get("number_of_pages")
    )


@require_GET
def track_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
):
    """Return the tracking form for a media item."""
    instance_id = request.GET.get("instance_id")
    if instance_id:
        media = BasicMedia.objects.get_media(
            request.user,
            media_type,
            instance_id,
        )
    elif request.GET.get("is_create"):
        media = None
    else:
        # no specific instance, try to find the first one
        user_medias = BasicMedia.objects.filter_media(
            request.user,
            media_id,
            media_type,
            source,
            season_number=season_number,
        )
        media = user_medias.first()
        if media:
            instance_id = media.id

    initial_data = {
        "media_id": media_id,
        "source": source,
        "media_type": media_type,
        "season_number": season_number,
        "instance_id": instance_id,
    }

    # Status sheet on untracked media opens this view with a preset status,
    # so picking "Completed" / "Planning" etc. from the popover lands the user
    # in a drawer with that status already chosen.
    initial_status = request.GET.get("status")
    if initial_status and initial_status in {s.value for s in Status}:
        initial_data["status"] = initial_status

    if media:
        title = media.item
        if media_type == MediaTypes.GAME.value:
            initial_data["progress"] = config.format_progress(
                media_type,
                media.progress,
            )
        # Pull release / air date for the quick-fill button next to the
        # start_date / end_date inputs. Soft-fail to None — if metadata
        # is gone or the provider is down, the buttons just don't render.
        release_date_iso = None
        try:
            meta = services.get_media_metadata(
                media_type,
                media_id,
                source,
                [season_number],
            )
            release_date_iso = _release_date_iso(meta)
        except services.ProviderAPIError:
            pass
    else:
        meta = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
        )
        title = meta["title"]
        if media_type == MediaTypes.SEASON.value:
            title += f" S{season_number}"
        release_date_iso = _release_date_iso(meta)

    form = get_form_class(media_type)(instance=media, initial=initial_data)

    book_total_pages = (
        _fetch_book_total_pages(media_id, source)
        if media_type == MediaTypes.BOOK.value
        else None
    )

    return render(
        request,
        "app/components/fill_track.html",
        {
            "title": title,
            "form": form,
            "media": media,
            "media_type": media_type,
            "return_url": request.GET["return_url"],
            "book_total_pages": book_total_pages,
            "release_date_iso": release_date_iso,
        },
    )


@require_POST
def media_save(request):
    """Save or update media data to the database."""
    media_id = request.POST["media_id"]
    source = request.POST["source"]
    media_type = request.POST["media_type"]
    season_number = request.POST.get("season_number")
    instance_id = request.POST.get("instance_id")

    if instance_id:
        instance = BasicMedia.objects.get_media(
            request.user,
            media_type,
            instance_id,
        )
    else:
        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
        )
        item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            defaults={
                "title": metadata["title"],
                "image": metadata["image"],
            },
        )
        model = apps.get_model(app_label="app", model_name=media_type)
        instance = model(item=item, user=request.user)

    # Validate the form and save the instance if it's valid
    form_class = get_form_class(media_type)
    form = form_class(request.POST, instance=instance)

    # Per-save override for the bulk completion date used when a Season is
    # marked Completed and child episodes get auto-stamped. Stashed on the
    # instance so Season.get_remaining_eps can read it without changing the
    # form/model signatures. Anything outside the known choice values falls
    # back silently to the user's global pref.
    completion_mode = request.POST.get("completion_date_mode")
    if (
        media_type == MediaTypes.SEASON.value
        and completion_mode in QuickWatchDateChoices.values
    ):
        instance._completion_date_override = completion_mode

    if form.is_valid():
        form.save()
        logger.info("%s saved successfully.", form.instance)
    else:
        logger.error(form.errors.as_json())
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(
                    request,
                    f"{field.replace('_', ' ').title()}: {error}",
                )

    return helpers.redirect_back(request)


@require_POST
def media_delete(request):
    """Delete media data from the database."""
    instance_id = request.POST["instance_id"]
    media_type = request.POST["media_type"]
    model = apps.get_model(app_label="app", model_name=media_type)

    try:
        media = BasicMedia.objects.get_media(
            request.user,
            media_type,
            instance_id,
        )
        media.delete()
        logger.info("%s deleted successfully.", media)

    except model.DoesNotExist:
        logger.warning("The %s was already deleted before.", media_type)

    return helpers.redirect_back(request)


def _release_date_iso(meta):
    """Extract a YYYY-MM-DD release / air date from media metadata.

    Different providers stash this under different keys
    (``release_date`` for movies, ``first_air_date`` for TV, ``released``
    for Discogs records, etc.). Returns the first one that looks
    parseable, or None. The string is sliced to the first 10 chars so
    full ISO timestamps with time-of-day get trimmed cleanly into the
    ``YYYY-MM-DD`` shape both HTML date inputs and datetime-local
    inputs (with a ``T00:00`` suffix) accept.
    """
    if not meta:
        return None
    details = meta.get("details") or {}
    candidates = (
        details.get("release_date"),
        details.get("first_air_date"),
        details.get("released"),
        meta.get("release_date"),
        meta.get("first_air_date"),
    )
    iso_date_length = len("YYYY-MM-DD")
    for value in candidates:
        if not value:
            continue
        text = str(value).strip()
        if len(text) >= iso_date_length and text[4] == "-" and text[7] == "-":
            return text[:iso_date_length]
    return None


@require_POST
def toggle_browse_language(request):
    """Flip the English-only Browse filter and bounce back to the referrer.

    Posts back to whatever page the toggle was triggered from (Browse,
    typically). We deliberately don't accept a target state in the
    payload — the button is a pure flip, which is easier to reason
    about than an idempotent set call and matches how Yamtrack's
    other inline toggles work.
    """
    user = request.user
    user.browse_include_non_english = not user.browse_include_non_english
    user.save(update_fields=["browse_include_non_english"])
    return redirect(request.headers.get("referer") or "browse")


@require_POST
def dismiss_item(request):
    """Record that the user marked a Browse tile 'not interested'.

    Idempotent: re-dismissing the same tile is a no-op. Returns 204 so
    the HTMX caller can swap the card out of the DOM via hx-swap=delete
    without any markup ping-pong; falls back to a referer redirect for
    non-HTMX clients (mostly tests).
    """
    source = request.POST.get("source", "").strip()
    media_type = request.POST.get("media_type", "").strip()
    media_id = request.POST.get("media_id", "").strip()
    title = request.POST.get("title", "").strip()[:255]

    if not (source and media_type and media_id):
        return HttpResponseBadRequest("missing source/media_type/media_id")
    if source not in Sources.values or media_type not in MediaTypes.values:
        return HttpResponseBadRequest("unknown source or media_type")

    DismissedItem.objects.get_or_create(
        user=request.user,
        source=source,
        media_type=media_type,
        media_id=media_id,
        defaults={"title": title},
    )

    if request.headers.get("HX-Request"):
        # 200 (not 204) so hx-swap="delete" actually fires — HTMX skips
        # the swap on 204 responses.
        return HttpResponse(b"")
    return redirect(request.headers.get("referer") or "browse")


@require_POST
def mark_user_messages_shown(request):
    """Mark all unseen persistent messages for the user as shown."""
    message_ids = [
        int(message_id)
        for message_id in request.POST.getlist("message_ids")
        if message_id.isdigit()
    ]
    if not message_ids:
        return HttpResponse(status=204)

    UserMessage.objects.filter(
        id__in=message_ids,
        user=request.user,
        shown_at__isnull=True,
    ).update(shown_at=timezone.now())
    return HttpResponse(status=204)


@require_POST
def episode_save(request):
    """Handle the creation, deletion, and updating of episodes for a season."""
    media_id = request.POST["media_id"]
    season_number = int(request.POST["season_number"])
    episode_number = int(request.POST["episode_number"])
    source = request.POST["source"]

    form = EpisodeForm(request.POST)
    if not form.is_valid():
        logger.error("Form validation failed: %s", form.errors)
        return HttpResponseBadRequest("Invalid form data")

    try:
        related_season = Season.objects.get(
            item__media_id=media_id,
            item__source=source,
            item__season_number=season_number,
            item__episode_number=None,
            user=request.user,
        )
    except Season.DoesNotExist:
        tv_with_seasons_metadata = services.get_media_metadata(
            "tv_with_seasons",
            media_id,
            source,
            [season_number],
        )
        season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]

        item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=season_number,
            defaults={
                "title": tv_with_seasons_metadata["title"],
                "image": season_metadata["image"],
            },
        )
        related_season = Season.objects.create(
            item=item,
            user=request.user,
            score=None,
            status=Status.IN_PROGRESS.value,
            notes="",
        )

        logger.info("%s did not exist, it was created successfully.", related_season)

    related_season.watch(episode_number, form.cleaned_data["end_date"])

    return helpers.redirect_back(request)


@require_http_methods(["GET", "POST"])
def create_entry(request):
    """Return the form for manually adding media items."""
    if request.method == "GET":
        media_types = MediaTypes.values
        return render(request, "app/create_entry.html", {"media_types": media_types})

    # Process the form submission
    form = ManualItemForm(request.POST, user=request.user)
    if not form.is_valid():
        # Handle form validation errors
        logger.error(form.errors.as_json())
        helpers.form_error_messages(form, request)
        return redirect("create_entry")

    # Try to save the item
    try:
        item = form.save()
    except IntegrityError:
        # Handle duplicate item
        media_name = form.cleaned_data["title"]
        if form.cleaned_data.get("season_number"):
            media_name += f" - Season {form.cleaned_data['season_number']}"
        if form.cleaned_data.get("episode_number"):
            media_name += f" - Episode {form.cleaned_data['episode_number']}"

        logger.exception("%s already exists in the database.", media_name)
        messages.error(request, f"{media_name} already exists in the database.")
        return redirect("create_entry")

    # Prepare and validate the media form
    updated_request = request.POST.copy()
    updated_request.update({"source": item.source, "media_id": item.media_id})
    media_form = get_form_class(item.media_type)(updated_request)

    if not media_form.is_valid():
        # Handle media form validation errors
        logger.error(media_form.errors.as_json())
        helpers.form_error_messages(media_form, request)

        # Delete the item since the media creation failed
        item.delete()
        logger.info("%s was deleted due to media form validation failure", item)
        return redirect("create_entry")

    # Save the media instance
    media_form.instance.user = request.user
    media_form.instance.item = item

    # Handle relationships based on media type
    if item.media_type == MediaTypes.SEASON.value:
        media_form.instance.related_tv = form.cleaned_data["parent_tv"]
    elif item.media_type == MediaTypes.EPISODE.value:
        media_form.instance.related_season = form.cleaned_data["parent_season"]

    media_form.save()

    # Success message
    msg = f"{item} added successfully."
    messages.success(request, msg)
    logger.info(msg)

    return redirect("create_entry")


@require_GET
def search_parent_tv(request):
    """Return the search results for parent TV shows."""
    query = request.GET.get("q", "").strip()

    if len(query) <= 1:
        return render(request, "app/components/search_parent_tv.html")

    logger.debug(
        "%s - Searching for TV shows with query: %s",
        request.user.username,
        query,
    )

    parent_tvs = TV.objects.filter(
        user=request.user,
        item__source=Sources.MANUAL.value,
        item__media_type=MediaTypes.TV.value,
        item__title__icontains=query,
    )[:5]

    return render(
        request,
        "app/components/search_parent_tv.html",
        {"results": parent_tvs, "query": query},
    )


@require_GET
def search_parent_season(request):
    """Return the search results for parent seasons."""
    query = request.GET.get("q", "").strip()

    if len(query) <= 1:
        return render(request, "app/components/search_parent_tv.html")

    logger.debug(
        "%s - Searching for seasons with query: %s",
        request.user.username,
        query,
    )

    parent_seasons = Season.objects.filter(
        user=request.user,
        item__source=Sources.MANUAL.value,
        item__media_type=MediaTypes.SEASON.value,
        item__title__icontains=query,
    )[:5]

    return render(
        request,
        "app/components/search_parent_season.html",
        {"results": parent_seasons, "query": query},
    )


@require_GET
def history_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the history page for a media item."""
    user_medias = BasicMedia.objects.filter_media(
        request.user,
        media_id,
        media_type,
        source,
        season_number=season_number,
        episode_number=episode_number,
    )

    total_medias = user_medias.count()
    timeline_entries = []
    for index, media in enumerate(user_medias, start=1):
        if history := media.history.all():
            media_entry_number = total_medias - index + 1
            timeline_entries.extend(
                history_processor.process_history_entries(
                    history,
                    media_type,
                    media_entry_number,
                    request.user,
                ),
            )
    return render(
        request,
        "app/components/fill_history.html",
        {
            "media_type": media_type,
            "timeline": timeline_entries,
            "total_medias": total_medias,
            "return_url": request.GET["return_url"],
        },
    )


@require_http_methods(["DELETE"])
def delete_history_record(request, media_type, history_id):
    """Delete a specific history record."""
    try:
        historical_model = apps.get_model(
            app_label="app",
            model_name=f"historical{media_type.lower()}",
        )

        historical_model.objects.get(
            history_id=history_id,
            history_user=request.user,
        ).delete()

        logger.info(
            "Deleted history record %s",
            str(history_id),
        )

        # Return empty 200 response - the element will be removed by HTMX
        return HttpResponse()

    except historical_model.DoesNotExist:
        logger.exception(
            "History record %s not found for user %s",
            str(history_id),
            str(request.user),
        )
        return HttpResponse("Record not found", status=404)


@require_GET
def statistics(request):
    """Return the statistics page."""
    # Set default date range to last year
    timeformat = "%Y-%m-%d"
    today = timezone.localdate()
    one_year_ago = today.replace(year=today.year - 1)

    # Get date parameters with defaults
    start_date_str = request.GET.get("start-date") or one_year_ago.strftime(timeformat)
    end_date_str = request.GET.get("end-date") or today.strftime(timeformat)

    if start_date_str == "all" and end_date_str == "all":
        start_date = None
        end_date = None
    else:
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)

        if start_date and end_date:
            # Convert to datetime with timezone awareness
            start_date = timezone.make_aware(
                datetime.combine(start_date, datetime.min.time()),
            )

            # End date should be end of day
            end_date = timezone.make_aware(
                datetime.combine(end_date, datetime.max.time()),
            )

    # Get all user media data in a single operation
    user_media, media_count = stats.get_user_media(
        request.user,
        start_date,
        end_date,
    )

    # Calculate all statistics from the retrieved data
    media_type_distribution = stats.get_media_type_distribution(
        media_count,
    )
    score_distribution, top_rated = stats.get_score_distribution(user_media)
    status_distribution = stats.get_status_distribution(user_media)
    status_pie_chart_data = stats.get_status_pie_chart_data(
        status_distribution,
    )
    timeline = stats.get_timeline(user_media)

    activity_data = stats.get_activity_data(request.user, start_date, end_date)

    context = {
        "start_date": start_date,
        "end_date": end_date,
        "media_count": media_count,
        "activity_data": activity_data,
        "media_type_distribution": media_type_distribution,
        "score_distribution": score_distribution,
        "top_rated": top_rated,
        "status_distribution": status_distribution,
        "status_pie_chart_data": status_pie_chart_data,
        "timeline": timeline,
        "date_format_values": DateFormatChoices.values,
    }

    return render(request, "app/statistics.html", context)


def wrapped(request, year=None):
    """Year-in-review recap page (Spotify-Wrapped style for media tracking)."""
    today = timezone.localdate()
    current_year = today.year

    if year is None:
        year = current_year

    # Three-year selector chips plus an "All time" link that just bounces to
    # the regular /statistics page (which already handles unbounded ranges).
    year_options = [current_year, current_year - 1, current_year - 2]

    recap = stats.get_year_in_review(request.user, year)

    context = {
        "recap": recap,
        "year": year,
        "current_year": current_year,
        "year_options": year_options,
    }
    return render(request, "app/wrapped.html", context)


def ensure_record_tracks(item):
    """Lazily fetch + persist the tracklist for a Discogs record Item.

    Returns the list of Track rows. Hits Discogs only on the first call
    per record (the result is cached by the provider, and tracks are
    persisted afterwards). Returns [] for non-Discogs records or when
    the API call fails — callers should fall back to album-level plays.
    """
    if (
        item.media_type != MediaTypes.RECORD.value
        or item.source != Sources.DISCOGS.value
    ):
        return list(item.tracks.all())

    existing = list(item.tracks.all())
    if existing:
        return existing

    try:
        rows = discogs.tracks(item.media_id)
    except Exception:
        logger.exception("Failed to fetch Discogs tracklist for %s", item)
        return []

    Track.objects.bulk_create(
        [
            Track(
                record_item=item,
                position=row["position"],
                side=row["side"],
                track_number=row["track_number"],
                title=row["title"],
                artist=row["artist"],
                duration_seconds=row["duration_seconds"],
            )
            for row in rows
        ],
        ignore_conflicts=True,
    )
    return list(item.tracks.all())


@require_POST
def log_record_spin(request, source, media_id):
    """Log a vinyl spin (manual play) for a record.

    Side comes from POST data — any letter "A".."Z" or "full". One Play row
    is inserted per track on the chosen side (or every track for "full"),
    so listening history mirrors how scrobbles look. Records without an
    available tracklist fall back to a single album-level Play.

    The Item row is created lazily here so users can log a spin straight
    from the detail page without first adding the record to their tracker.

    Returns the rendered status fragment so HTMX can swap it into the
    detail page.
    """
    side = request.POST.get("side", "full")
    if side not in PlaySide.values:
        return HttpResponseBadRequest(f"Unknown side {side!r}")

    item = Item.objects.filter(
        media_id=media_id,
        source=source,
        media_type=MediaTypes.RECORD.value,
    ).first()
    if item is None:
        try:
            metadata = services.get_media_metadata(
                MediaTypes.RECORD.value,
                media_id,
                source,
            )
        except services.ProviderAPIError:
            return HttpResponseBadRequest("Record not found.")
        item, _ = Item.objects.get_or_create(
            media_id=str(media_id),
            source=source,
            media_type=MediaTypes.RECORD.value,
            defaults={
                "title": metadata.get("title") or "",
                "image": metadata.get("image") or "",
                "artist": (metadata.get("details") or {}).get("artist") or "",
            },
        )

    tracks = ensure_record_tracks(item)
    if side == PlaySide.FULL.value:
        side_tracks = tracks
    else:
        side_tracks = [t for t in tracks if t.side == side]

    now = timezone.now()
    if side_tracks:
        Play.objects.bulk_create(
            [
                Play(
                    user=request.user,
                    item=item,
                    track=t,
                    artist=t.artist or item.artist,
                    title=t.title,
                    album=item.title,
                    played_at=now,
                    source=PlaySource.MANUAL_VINYL.value,
                    side=t.side or side,
                )
                for t in side_tracks
            ],
        )
    else:
        Play.objects.create(
            user=request.user,
            item=item,
            artist=item.artist,
            title=item.title,
            played_at=now,
            source=PlaySource.MANUAL_VINYL.value,
            side=side,
        )

    plays = Play.objects.filter(user=request.user, item=item)
    context = {
        "record_spin": plays.order_by("-played_at").first(),
        "record_spin_count": plays.count(),
    }
    return render(request, "app/components/record_spin.html", context)


@require_GET
def music_history(request):
    """Render the listening history: filterable, paginated list of Play rows.

    Surfaces both manual vinyl spins and ListenBrainz scrobbles so unmatched
    listens (no Item resolved by artist+title) are visible somewhere in the UI
    instead of only in the database.
    """
    source_filter = request.GET.get("source", "all")
    match_filter = request.GET.get("match", "all")
    days_param = request.GET.get("days", "30")

    qs = Play.objects.filter(user=request.user).select_related("item", "track")
    if source_filter in PlaySource.values:
        qs = qs.filter(source=source_filter)
    if match_filter == "matched":
        qs = qs.exclude(item=None)
    elif match_filter == "unmatched":
        qs = qs.filter(item=None)

    if days_param != "all":
        try:
            days = max(int(days_param), 1)
        except ValueError:
            days = 30
            days_param = "30"
        qs = qs.filter(played_at__gte=timezone.now() - timedelta(days=days))

    total = qs.count()
    matched = qs.exclude(item=None).count()
    top_artists = list(
        qs.exclude(artist="")
        .values("artist")
        .annotate(play_count=Count("id"))
        .order_by("-play_count")[:10],
    )

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "total": total,
        "matched_count": matched,
        "unmatched_count": total - matched,
        "top_artists": top_artists,
        "source_filter": source_filter,
        "match_filter": match_filter,
        "days": days_param,
        "play_sources": PlaySource.choices,
    }
    return render(request, "app/music_history.html", context)


@require_GET
def music_unmatched(request):
    """Triage page for ListenBrainz scrobbles with no resolved Item.

    Groups unmatched Plays by (artist, album) so a user with hundreds of
    unmatched listens can fix the *album* once and back-link every spin
    of it in one move. Falls back to (artist, title) when album is blank
    (singles, podcast scrobbles, anything Discogs doesn't have on a
    canonical release).
    """
    base = Play.objects.filter(user=request.user, item__isnull=True).exclude(artist="")

    # Album-keyed groups first — these are the high-value matches because
    # one click links N spins to a single Record. Excludes blank album so
    # singles don't collapse into one giant "<no album>" bucket.
    album_groups = (
        base.exclude(album="")
        .values("artist", "album")
        .annotate(
            plays=Count("id"),
            last_played=Max("played_at"),
        )
        .order_by("-plays")[:30]
    )

    # Singles fallback: scrobbles with no album text. Group by track title.
    single_groups = (
        base.filter(album="")
        .values("artist", "title")
        .annotate(
            plays=Count("id"),
            last_played=Max("played_at"),
        )
        .order_by("-plays")[:15]
    )

    total_unmatched = base.count()

    return render(
        request,
        "app/music_unmatched.html",
        {
            "album_groups": list(album_groups),
            "single_groups": list(single_groups),
            "total_unmatched": total_unmatched,
        },
    )


@require_GET
def match_record_search(request):
    """htmx-driven search of the user's tracked Records for the resolver."""
    query = request.GET.get("q", "").strip()
    # Group context — flows back into each Match button so apply() has
    # everything it needs in one POST.
    ctx = {
        "group_key": request.GET.get("k", ""),
        "kind": request.GET.get("kind", "album"),
        "artist": request.GET.get("artist", ""),
        "album": request.GET.get("album", ""),
        "title": request.GET.get("title", ""),
    }
    if len(query) < 2:  # noqa: PLR2004 — need at least two chars before searching
        ctx["results"] = []
    else:
        ctx["results"] = list(
            Record.objects.filter(
                user=request.user,
                item__title__icontains=query,
            )
            .select_related("item")
            .order_by("-progressed_at", "-created_at")[:5],
        )
    return render(request, "app/components/match_record_results.html", ctx)


@require_POST
def match_unmatched_apply(request):
    """Backfill `item` on every unmatched Play for an (artist, album|title) group.

    POST fields:
        artist  Required — the artist string to match on.
        album   The album string; ignored when blank.
        title   The track title; used only when ``album`` is blank (singles).
        item_id Required — Item.id of the tracked Record to link to.

    Returns 200 with a swap fragment that removes the resolved row from
    the UI on success.
    """
    artist = (request.POST.get("artist") or "").strip()
    album = (request.POST.get("album") or "").strip()
    title = (request.POST.get("title") or "").strip()
    item_id = request.POST.get("item_id")

    if not artist or not item_id:
        return HttpResponseBadRequest("artist and item_id are required")

    # Make sure the target item is actually a Record the user tracks —
    # without this any logged-in user could backfill plays against
    # arbitrary record IDs they discovered out-of-band.
    try:
        item = Item.objects.get(
            id=int(item_id),
            media_type=MediaTypes.RECORD.value,
            record__user=request.user,
        )
    except (Item.DoesNotExist, ValueError):
        return HttpResponseBadRequest("invalid item_id")

    qs = Play.objects.filter(
        user=request.user,
        item__isnull=True,
        artist=artist,
    )
    qs = qs.filter(album=album) if album else qs.filter(album="", title=title)

    updated = qs.update(item=item)
    logger.info(
        "Matched %d unmatched plays to record %s for user %s",
        updated,
        item,
        request.user,
    )

    # Empty 200 with HX-Trigger so the page can show a small toast. The
    # `hx-swap=delete` on the calling button is what actually removes the
    # row from the DOM, so we don't need a body.
    return HttpResponse(
        status=200,
        headers={
            "HX-Trigger": json.dumps(
                {"matched": {"count": updated, "title": item.title}},
            ),
        },
    )


@require_GET
def music_stats(request):
    """Music listening dashboard: charts and breakdowns over a date window.

    ``?days=`` accepts 7/30/90/365 or "all". Defaults to the last year.
    All aggregation happens in stats.get_music_stats.
    """
    days_param = request.GET.get("days", "365")
    if days_param == "all":
        days = None
    else:
        try:
            days = max(int(days_param), 1)
        except ValueError:
            days = 365
            days_param = "365"

    context = {
        "music": stats.get_music_stats(request.user, days=days),
        "days": days_param,
    }
    return render(request, "app/music_stats.html", context)


@require_GET
def cmdk_search(request):
    """Search the user's tracked library for the command palette.

    Returns a small HTML partial of up to ~12 results grouped by media type.
    Intentionally library-scoped (not a TMDB/MAL search) — the full /search
    page covers discovery; this is the "find that show I'm watching" path.
    """
    query = request.GET.get("q", "").strip()
    if len(query) < 2:  # noqa: PLR2004 — need at least two chars before searching
        return render(request, "app/components/cmdk_results.html", {"results": []})

    per_type_limit = 3
    cmdk_max_results = 12
    results = []
    # Walk concrete media types (skip Episode — those are sub-items of seasons
    # and shouldn't surface in the global jump list).
    for media_type in MediaTypes.values:
        if media_type == MediaTypes.EPISODE.value:
            continue
        model = apps.get_model("app", media_type)
        rows = (
            model.objects.filter(user=request.user, item__title__icontains=query)
            .select_related("item")
            .order_by("-created_at")[:per_type_limit]
        )
        results.extend(
            {
                "item": media.item,
                "media_type": media_type,
                "status": getattr(media, "status", None),
            }
            for media in rows
        )
        if len(results) >= cmdk_max_results:
            break

    return render(
        request,
        "app/components/cmdk_results.html",
        {"results": results[:12], "query": query},
    )


@login_not_required
@require_GET
def service_worker(request):
    """Serve the service worker JS from the app root.

    Served at the app root (not from STATIC_URL) so the SW's effective scope
    is the whole app — important for BASE_URL subpath deploys where
    /static/... lives at /<base>/static/... and would limit scope to the
    static-js directory.

    Service-Worker-Allowed lets the SW claim a wider scope than its own URL.
    """
    response = render(
        request,
        "app/serviceworker.js",
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@login_not_required
@require_GET
def webmanifest(request):
    """Serve the PWA manifest as a template so URLs honor BASE_URL."""
    response = render(
        request,
        "app/site.webmanifest",
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response


@login_not_required
@require_GET
def offline(request):
    """Offline fallback page precached by the service worker.

    Kept standalone (no extends base.html) so the cached response renders
    correctly regardless of which user installed the SW.
    """
    response = render(request, "app/offline.html")
    response["Cache-Control"] = "no-cache"
    return response


@login_not_required
@require_GET
def badge_count(request):
    """Return the PWA app-icon badge count.

    Sums two signals so the installed icon's badge reflects "things waiting
    for you today":
      - calendar events airing today (user-local) on tracked media
      - 1 if there are any unseen What's New release-note entries

    Called from base.html on load; the value drives `navigator.setAppBadge`.
    Best-effort: any exception collapses to 0 so the badge never breaks UI.
    """
    from app import release_notes  # noqa: PLC0415 — cheap, view-only
    from events.models import Event  # noqa: PLC0415 — avoid app-load cycle

    if not request.user.is_authenticated:
        return JsonResponse({"count": 0})

    today = timezone.localdate()
    try:
        airing = Event.objects.get_user_events(request.user, today, today).count()
    except Exception:
        logger.exception("badge_count: failed to query today's events")
        airing = 0

    whats_new = 0
    last_seen = getattr(request.user, "last_seen_version", None)
    if last_seen != release_notes.CURRENT_FORK_VERSION and release_notes.entries_since(
        last_seen,
    ):
        whats_new = 1

    response = JsonResponse({"count": airing + whats_new})
    response["Cache-Control"] = "no-store"
    return response


# Provider URL patterns the Share Target intake recognises. Each entry maps a
# host (lowercased) to a callable that returns ``(media_type, provider_id)``
# given the parsed URL's path. Anything unrecognised falls through to /search.
_SHARE_TARGET_PROVIDERS = {
    "themoviedb.org": "tmdb",
    "www.themoviedb.org": "tmdb",
    "imdb.com": "imdb",
    "www.imdb.com": "imdb",
    "myanimelist.net": "mal",
    "anilist.co": "anilist",
}


_URL_PATTERN = re.compile(r"https?://\S+")


def _extract_first_url(*candidates):
    """Return the first http(s) URL found in the supplied strings."""
    for c in candidates:
        if not c:
            continue
        match = _URL_PATTERN.search(c)
        if match:
            return match.group(0).rstrip(".,;)")
    return None


@csrf_exempt
@require_http_methods(["GET", "POST"])
def share_intake(request):
    """Web Share Target handler.

    Browsers (or the OS) POST/GET ``title``, ``text``, and ``url`` from the
    system share sheet. We hunt for the first http(s) URL across all three
    fields and redirect to /search so the user lands somewhere useful — a
    follow-up can deep-link directly into provider create flows once we have
    per-provider URL parsers.

    CSRF is exempted because share sheets don't propagate the cookie /
    token pair; the login middleware still guarantees the user is signed in
    and a redirect to /search? doesn't mutate state.
    """
    data = request.POST if request.method == "POST" else request.GET
    shared_url = _extract_first_url(
        data.get("url"),
        data.get("text"),
        data.get("title"),
    )
    if shared_url:
        return redirect(f"{reverse('search')}?q={shared_url}")
    title = (data.get("title") or data.get("text") or "").strip()
    if title:
        return redirect(f"{reverse('search')}?q={title}")
    return redirect("home")
