import json
import logging
import zoneinfo

import apprise
from celery import current_app as celery_app
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_celery_beat.models import PeriodicTask

from app import config as app_config
from app.models import Item, MediaTypes
from app.providers import tmdb
from app.release_notes import CURRENT_FORK_VERSION
from integrations.models import WebhookEvent
from users.forms import NotificationSettingsForm, PasswordChangeForm, UserUpdateForm
from users.models import (
    DateFormatChoices,
    DensityChoices,
    FontChoices,
    QuickWatchDateChoices,
    ThemeChoices,
    TimeFormatChoices,
)

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def account(request):
    """Update the user's account and import/export data."""
    user_form = UserUpdateForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)

    if request.method == "POST":
        # Order matters: the password change form includes a hidden username
        # field (password-manager hint), so password keys must be checked
        # FIRST or the dispatch routes password submits to UserUpdateForm.
        is_password_post = any(
            key in request.POST
            for key in ["old_password", "new_password1", "new_password2"]
        )

        if is_password_post:
            password_form = PasswordChangeForm(user=request.user, data=request.POST)

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(
                    request,
                    user,
                )
                messages.success(request, "Your password has been updated!")
                logger.info(
                    "Successful password change for user: %s",
                    request.user.username,
                )
                return redirect("account")
            logger.warning(
                "Failed password change for user: %s - %s",
                request.user.username,
                list(password_form.errors.keys()),
            )

        elif "username" in request.POST:
            user_form = UserUpdateForm(request.POST, instance=request.user)

            if user_form.is_valid():
                user_form.save()
                messages.success(request, "Your username has been updated!")
                logger.info(
                    "Successful username change for user: %s",
                    request.user.username,
                )
                return redirect("account")
            logger.warning(
                "Failed username change for user: %s - %s",
                request.user.username,
                list(user_form.errors.keys()),
            )

    context = {
        "user_form": user_form,
        "password_form": password_form,
    }

    return render(request, "users/account.html", context)


@require_http_methods(["GET", "POST"])
def notifications(request):
    """Render the notifications settings page."""
    if request.method == "POST":
        form = NotificationSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification settings updated successfully!")
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, f"{error}")

        return redirect("notifications")

    form = NotificationSettingsForm(instance=request.user)

    return render(
        request,
        "users/notifications.html",
        {
            "form": form,
        },
    )


@require_GET
def search_items(request):
    """Search for items to exclude from notifications."""
    query = request.GET.get("q", "").strip()

    if not query or len(query) <= 1:
        return render(
            request,
            "users/components/search_results.html",
        )

    # Search for items that match the query
    items = (
        Item.objects.filter(
            Q(title__icontains=query),
        )
        .exclude(
            id__in=request.user.notification_excluded_items.values_list(
                "id",
                flat=True,
            ),
        )
        .distinct()[:10]
    )

    return render(
        request,
        "users/components/search_results.html",
        {"items": items, "query": query},
    )


@require_POST
def exclude_item(request):
    """Exclude an item from notifications."""
    item_id = request.POST["item_id"]
    item = get_object_or_404(Item, id=item_id)
    request.user.notification_excluded_items.add(item)

    # Return the updated excluded items list
    excluded_items = request.user.notification_excluded_items.all()

    return render(
        request,
        "users/components/excluded_items.html",
        {"excluded_items": excluded_items},
    )


@require_POST
def include_item(request):
    """Remove an item from the exclusion list."""
    item_id = request.POST["item_id"]
    item = get_object_or_404(Item, id=item_id)
    request.user.notification_excluded_items.remove(item)

    # Return the updated excluded items list
    excluded_items = request.user.notification_excluded_items.all()

    return render(
        request,
        "users/components/excluded_items.html",
        {"excluded_items": excluded_items},
    )


@require_GET
def test_notification(request):
    """Send a test notification to the user."""
    try:
        # Create Apprise instance
        apobj = apprise.Apprise()

        # Add all notification URLs
        notification_urls = [
            url.strip()
            for url in request.user.notification_urls.splitlines()
            if url.strip()
        ]
        if not notification_urls:
            messages.error(request, "No notification URLs configured.")
            return redirect("notifications")

        for url in notification_urls:
            apobj.add(url)

        # Send test notification
        result = apobj.notify(
            title="Yamtrack Test Notification",
            body=(
                "This is a test notification from Yamtrack. "
                "If you're seeing this, your notifications are working correctly!"
            ),
        )

        if result:
            messages.success(request, "Test notification sent successfully!")
        else:
            messages.error(request, "Failed to send test notification.")
    except Exception:
        logger.exception("Error sending notification")

    return redirect("notifications")


@require_GET
def push_vapid_key(request):  # noqa: ARG001 — Django view signature
    """Return the VAPID public key (or a disabled marker) for the client."""
    from users import push  # noqa: PLC0415 — keeps pywebpush import lazy

    if not push.push_enabled():
        return JsonResponse({"enabled": False, "publicKey": None})
    return JsonResponse(
        {"enabled": True, "publicKey": settings.VAPID_PUBLIC_KEY},
    )


@require_POST
def push_subscribe(request):
    """Persist a PushSubscription for this user.

    Re-subscribing the same endpoint updates the keys in place so a
    rotated p256dh/auth pair doesn't leave a stale row behind.
    """
    from users.models import PushSubscription  # noqa: PLC0415

    try:
        data = json.loads(request.body)
        endpoint = data["endpoint"]
        keys = data["keys"]
        p256dh = keys["p256dh"]
        auth = keys["auth"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return HttpResponse("Invalid subscription payload", status=400)

    ua = request.headers.get("user-agent", "")[:300]
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": ua,
        },
    )
    return JsonResponse({"ok": True})


@require_POST
def push_unsubscribe(request):
    """Remove a PushSubscription for this user."""
    from users.models import PushSubscription  # noqa: PLC0415

    try:
        data = json.loads(request.body)
        endpoint = data["endpoint"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return HttpResponse("Invalid unsubscribe payload", status=400)

    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@require_POST
def push_test(request):
    """Send a test push to every subscription on this user."""
    from users import push  # noqa: PLC0415

    if not push.push_enabled():
        messages.error(
            request,
            "Web Push is not configured (set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY).",
        )
        return redirect("notifications")

    count = push.push_to_user(
        request.user,
        title="Yamtrack — test push",
        body="Push notifications are working. You'll get release alerts here.",
        url=request.build_absolute_uri("/"),
    )
    if count > 0:
        messages.success(
            request,
            f"Sent test push to {count} subscription{'s' if count != 1 else ''}.",
        )
    else:
        messages.error(
            request,
            "No active push subscriptions found on this account.",
        )
    return redirect("notifications")


def _sanitize_streaming_providers(raw_values):
    """Filter a POST list of provider IDs against the curated allowlist.

    Returns a comma-separated string ready to drop into
    ``User.streaming_providers``. Reject anything that doesn't match a
    known entry so a tampered POST can't smuggle arbitrary IDs through.
    """
    known_provider_ids = {entry["id"] for entry in app_config.STREAMING_PROVIDERS}
    selected = []
    for raw in raw_values:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value in known_provider_ids:
            selected.append(str(value))
    return ",".join(selected)


@require_http_methods(["GET", "POST"])
def preferences(request):
    """Render the preferences settings page."""
    media_types = MediaTypes.values
    media_types.remove(MediaTypes.EPISODE.value)
    watch_provider_regions = tmdb.watch_provider_regions()
    subscribed_provider_ids = app_config.parse_streaming_providers(
        request.user.streaming_providers,
    )

    if request.method == "GET":
        return render(
            request,
            "users/preferences.html",
            {
                "media_types": media_types,
                "quick_watch_date_choices": QuickWatchDateChoices.choices,
                "date_format_choices": DateFormatChoices.choices,
                "time_format_choices": TimeFormatChoices.choices,
                "theme_choices": ThemeChoices.choices,
                "density_choices": DensityChoices.choices,
                "font_choices": FontChoices.choices,
                "watch_provider_choices": watch_provider_regions,
                "timezone_choices": sorted(zoneinfo.available_timezones()),
                "streaming_provider_choices": app_config.STREAMING_PROVIDERS,
                "subscribed_provider_ids": subscribed_provider_ids,
            },
        )

    # Prevent demo users from updating preferences
    if request.user.is_demo:
        messages.error(request, "This section is view-only for demo accounts.")
        return redirect("preferences")

    # Process form submission
    request.user.clickable_media_cards = "clickable_media_cards" in request.POST
    request.user.obfuscate_unseen_episodes = "obfuscate_unseen_episodes" in request.POST
    request.user.auto_mark_prior_episodes = "auto_mark_prior_episodes" in request.POST
    request.user.quick_watch_date = request.POST.get(
        "quick_watch_date",
        QuickWatchDateChoices.CURRENT_DATE,
    )
    request.user.progress_bar = "progress_bar" in request.POST
    request.user.hide_completed_recommendations = (
        "hide_completed_recommendations" in request.POST
    )
    request.user.hide_zero_rating = "hide_zero_rating" in request.POST
    request.user.date_format = request.POST.get(
        "date_format",
        DateFormatChoices.ISO,
    )
    request.user.time_format = request.POST.get(
        "time_format",
        TimeFormatChoices.HOUR_24,
    )
    theme_value = request.POST.get("theme", ThemeChoices.DEFAULT)
    if theme_value in ThemeChoices.values:
        request.user.theme = theme_value
    density_value = request.POST.get("density", DensityChoices.COMFORTABLE)
    if density_value in DensityChoices.values:
        request.user.density = density_value
    font_value = request.POST.get("font", FontChoices.SYSTEM)
    if font_value in FontChoices.values:
        request.user.font = font_value
    tz_value = (request.POST.get("timezone") or "").strip()
    if tz_value == "" or tz_value in zoneinfo.available_timezones():
        request.user.timezone = tz_value
    media_types_checked = request.POST.getlist("media_types_checkboxes")

    provider_region = request.POST.get("watch_provider_region", "")
    if provider_region in [region[0] for region in watch_provider_regions]:
        request.user.watch_provider_region = provider_region
    else:
        request.user.watch_provider_region = "UNSET"

    request.user.streaming_providers = _sanitize_streaming_providers(
        request.POST.getlist("streaming_providers"),
    )

    # Update user preferences for each media type
    for media_type in media_types:
        setattr(
            request.user,
            f"{media_type}_enabled",
            media_type in media_types_checked,
        )

    # Save changes and redirect
    request.user.save()
    messages.success(request, "Settings updated.")

    return redirect("preferences")


@require_GET
def integrations(request):
    """Render the integrations settings page."""
    from integrations.models import HardcoverIntegration  # noqa: PLC0415

    recent_webhook_events = list(
        WebhookEvent.objects.filter(user=request.user).order_by("-created_at")[:20],
    )
    hardcover_integration = HardcoverIntegration.objects.filter(
        user=request.user,
    ).first()
    return render(
        request,
        "users/integrations.html",
        {
            "recent_webhook_events": recent_webhook_events,
            "hardcover_integration": hardcover_integration,
        },
    )


@require_GET
def import_data(request):
    """Render the import data settings page."""
    import_tasks = request.user.get_import_tasks()
    return render(request, "users/import_data.html", {"import_tasks": import_tasks})


@require_GET
def export_data(request):
    """Render the export data settings page."""
    return render(request, "users/export_data.html")


@require_GET
def advanced(request):
    """Render the advanced settings page."""
    from datetime import timedelta  # noqa: PLC0415 — view-local to scope deps

    from django.apps import apps  # noqa: PLC0415
    from django.utils import timezone  # noqa: PLC0415

    from app.models import MediaTypes, Status  # noqa: PLC0415

    # Stale "In Progress" sweep — list items the user started but hasn't
    # touched in ~60 days, so they can quickly Pause or Drop them.
    # Walks every concrete media type (Episode excluded — it tracks via its
    # parent Season). Uses progressed_at (the MonitorField on progress) as
    # the "last activity" proxy and falls back to created_at when an item
    # was created but never moved.
    stale_cutoff = timezone.now() - timedelta(days=60)
    stale_items = []
    for media_type in MediaTypes.values:
        if media_type in (MediaTypes.EPISODE.value, MediaTypes.SEASON.value):
            continue
        model = apps.get_model("app", media_type)
        rows = model.objects.filter(
            user=request.user,
            status=Status.IN_PROGRESS.value,
        ).select_related("item")
        for media in rows:
            last_activity = media.progressed_at or media.created_at
            if last_activity and last_activity < stale_cutoff:
                stale_items.append(
                    {
                        "media": media,
                        "media_type": media_type,
                        "last_activity": last_activity,
                    },
                )
    # Oldest at the top — these are the most-likely-abandoned.
    stale_items.sort(key=lambda r: r["last_activity"])

    return render(
        request,
        "users/advanced.html",
        {"stale_items": stale_items},
    )


@require_GET
def about(request):
    """Render the about page."""
    return render(request, "users/about.html", {"version": settings.VERSION})


@require_GET
def onboarding(request):
    """Render the post-signup onboarding wizard.

    Currently this is a single-page surface that walks the user through three
    quick steps: pick the media types they track, see the import options
    available, and pick a theme. The form posts to the existing preferences
    endpoint and `import_data` for actual changes, so this view is read-only.

    The plan calls for redirecting brand-new users here on first login, gated
    on a User.onboarded boolean — that gating is deferred until the field
    lands in a follow-up migration. The route is reachable manually today.
    """
    return render(
        request,
        "users/onboarding.html",
        {
            "media_types": MediaTypes.values,
            "theme_choices": ThemeChoices.choices,
        },
    )


@require_POST
def delete_import_schedule(request):
    """Delete an import schedule."""
    task_name = request.POST.get("task_name")
    try:
        task = PeriodicTask.objects.get(
            name=task_name,
            kwargs__contains=f'"user_id": {request.user.id}',
        )
        task.delete()
        messages.success(request, "Import schedule deleted.")
    except PeriodicTask.DoesNotExist:
        messages.error(request, "Import schedule not found.")
    return redirect("import_data")


@require_POST
def run_import_schedule_now(request):
    """Trigger a scheduled import immediately without waiting for the crontab.

    Looks up the user's PeriodicTask by name, then dispatches the underlying
    Celery task with the stored kwargs. Authorisation is scoped to the
    request user via the kwargs lookup (each task's kwargs dict embeds
    user_id), so users can't kick off other people's imports.
    """
    task_name = request.POST.get("task_name")
    try:
        periodic_task = PeriodicTask.objects.get(
            name=task_name,
            kwargs__contains=f'"user_id": {request.user.id}',
        )
    except PeriodicTask.DoesNotExist:
        messages.error(request, "Import schedule not found.")
        return redirect("import_data")

    celery_task = celery_app.tasks.get(periodic_task.task)
    if celery_task is None:
        messages.error(request, f"Unknown task: {periodic_task.task}")
        return redirect("import_data")

    try:
        kwargs = json.loads(periodic_task.kwargs or "{}")
    except json.JSONDecodeError:
        messages.error(request, "Stored task kwargs are corrupted.")
        return redirect("import_data")

    celery_task.apply_async(kwargs=kwargs)
    messages.success(request, f"{periodic_task.task} queued.")
    return redirect("import_data")


@require_POST
def regenerate_token(request):
    """Regenerate the token for the user."""
    while True:
        try:
            request.user.regenerate_token()
            messages.success(request, "Token regenerated successfully.")
            break
        except IntegrityError:
            continue
    return redirect("integrations")


@require_POST
def update_plex_usernames(request):
    """Update the Plex usernames for the user."""
    usernames = request.POST.get("plex_usernames", "")

    username_list = [u.strip() for u in usernames.split(",") if u.strip()]

    seen = set()
    deduplicated_usernames = [
        u for u in username_list if not (u in seen or seen.add(u))
    ]

    # Reconstruct with comma-space separation
    cleaned_usernames = ", ".join(deduplicated_usernames)

    if cleaned_usernames != request.user.plex_usernames:
        request.user.plex_usernames = cleaned_usernames
        request.user.save(update_fields=["plex_usernames"])
        messages.success(request, "Plex usernames updated successfully")

    return redirect("integrations")


@require_POST
def update_suwayomi_url(request):
    """Update the Suwayomi base URL for the user."""
    raw = request.POST.get("suwayomi_url", "").strip().rstrip("/")

    if raw == request.user.suwayomi_url:
        return redirect("integrations")

    user = request.user
    user.suwayomi_url = raw
    try:
        user.full_clean(exclude=None, validate_unique=False)
    except ValidationError as exc:
        for msg in exc.message_dict.get("suwayomi_url", ["Invalid Suwayomi URL"]):
            messages.error(request, msg)
        return redirect("integrations")

    user.save(update_fields=["suwayomi_url"])
    if raw:
        messages.success(request, "Suwayomi URL saved")
    else:
        messages.success(request, "Suwayomi URL cleared")
    return redirect("integrations")


@require_POST
def dismiss_whats_new(request):
    """Record that the user has seen the current release-notes batch."""
    if request.user.last_seen_version != CURRENT_FORK_VERSION:
        request.user.last_seen_version = CURRENT_FORK_VERSION
        request.user.save(update_fields=["last_seen_version"])
    return HttpResponse(status=204)


@require_POST
def clear_search_cache(request):
    """Clear all cached search entries."""
    deleted = cache.delete_pattern("search_*")

    messages.success(
        request,
        f"Successfully cleared {deleted} search entr{pluralize(deleted, 'y,ies')}",
    )
    logger.info(
        "Successfully cleared %s search entries",
        deleted,
    )

    return redirect("advanced")
