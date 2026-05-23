import calendar as cal
import logging
from datetime import UTC, date, timedelta

import icalendar
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from events import tasks
from events.models import Event
from users.models import User

logger = logging.getLogger(__name__)


def _clamped_int(raw, *, default, lo, hi):
    """Parse a query-string integer with a default and inclusive bounds."""
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def build_calendar_context(user, month=None, year=None, view_type=None):
    """Build the context dict needed to render the calendar card."""
    if view_type is None:
        view_type = user.calendar_layout

    try:
        current_date = (
            date(int(year), int(month), 1) if month and year else timezone.localdate()
        )
        month, year = current_date.month, current_date.year
    except (ValueError, TypeError):
        logger.warning("Invalid month or year provided: %s, %s", month, year)
        current_date = timezone.localdate()
        month, year = current_date.month, current_date.year

    is_december = month == 12  # noqa: PLR2004
    is_january = month == 1

    prev_month = 12 if is_january else month - 1
    prev_year = year - 1 if is_january else year

    next_month = 1 if is_december else month + 1
    next_year = year + 1 if is_december else year

    first_day = date(year, month, 1)
    last_day = date(
        year + 1 if is_december else year,
        1 if is_december else month + 1,
        1,
    ) - timedelta(days=1)

    calendar_format = cal.monthcalendar(year, month)
    month_name = cal.month_name[month]

    releases = Event.objects.get_user_events(user, first_day, last_day)

    release_dict = {}
    for release in releases:
        local_datetime = timezone.localtime(release.datetime)
        day = local_datetime.day
        if day not in release_dict:
            release_dict[day] = []
        release_dict[day].append(release)

    return {
        "calendar": calendar_format,
        "month": month,
        "month_name": month_name,
        "year": year,
        "prev_month": prev_month,
        "prev_year": prev_year,
        "next_month": next_month,
        "next_year": next_year,
        "release_dict": release_dict,
        "today": timezone.localdate(),
        "view_type": view_type,
    }


@require_GET
def calendar(request):
    """Display the calendar page."""
    view_type = request.user.update_preference(
        "calendar_layout",
        request.GET.get("view"),
    )

    context = build_calendar_context(
        request.user,
        month=request.GET.get("month"),
        year=request.GET.get("year"),
        view_type=view_type,
    )
    return render(request, "events/calendar.html", context)


@require_POST
def reload_calendar(request):
    """Refresh the calendar with the latest dates."""
    tasks.reload_calendar.delay(request.user)
    messages.info(request, "The task to refresh upcoming releases has been queued.")
    return redirect("calendar")


@login_not_required
@csrf_exempt
@require_http_methods(["GET", "HEAD", "PROPFIND"])
def download_calendar(request, token: str):
    """Download the calendar as a iCalendar file.

    Optional query params:
        types  Comma-separated media types to include (default: all enabled).
               Example: ?types=tv,movie keeps only TV + movie events.
        days_before  Days of past events to include (default 30, max 365).
        days_after   Days of future events to include (default 90, max 365).
    """
    try:
        user = User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Calendar request: Invalid token: %s",
            token,
        )
        return HttpResponse(status=401)

    now = timezone.now()

    days_before = _clamped_int(request.GET.get("days_before"), default=30, lo=0, hi=365)
    days_after = _clamped_int(request.GET.get("days_after"), default=90, lo=0, hi=365)

    start_date = now.date() - timedelta(days=days_before)
    end_date = now.date() + timedelta(days=days_after)

    # Retrieve release events
    releases = Event.objects.get_user_events(user, start_date, end_date)

    # Optional media-type filter — keeps the underlying query unchanged but
    # drops events for types the subscriber doesn't want. Cheap because the
    # default window is small (~120 days).
    types_param = request.GET.get("types", "").strip()
    if types_param:
        wanted = {t for t in types_param.split(",") if t}
        releases = [r for r in releases if r.item.media_type in wanted]

    # Create iCalendar object
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Yamtrack//EN")
    cal.add("version", "2.0")

    for release in releases:
        cal_event = icalendar.Event()
        cal_event.add("uid", release.id)
        cal_event.add("summary", str(release))
        dt_tz_aware = release.datetime.replace(tzinfo=UTC)
        cal_event.add("dtstart", dt_tz_aware)
        cal_event.add("dtend", dt_tz_aware)
        cal_event.add("dtstamp", now)
        cal.add_component(cal_event)

    # Return the iCal file
    response = HttpResponse(cal.to_ical(), content_type="text/calendar")
    response["Content-Disposition"] = 'attachment; filename="calendar.ics"'
    return response


@login_not_required
@csrf_exempt
@require_http_methods(["GET", "HEAD", "PROPFIND"])
def download_list_calendar(request, token: str, list_id: int):
    """Per-list iCal feed.

    Returns release events restricted to items in the given CustomList.
    Authorisation: the token's owning user must be able to view the list
    (owner or collaborator). Supports the same ``days_before`` and
    ``days_after`` clamps as the global calendar feed so subscribers can
    tighten the window without losing the per-list scoping.
    """
    try:
        user = User.objects.get(token=token)
    except ObjectDoesNotExist:
        return HttpResponse(status=401)

    try:
        from lists.models import CustomList
        custom_list = CustomList.objects.get(pk=list_id)
    except (ObjectDoesNotExist, ImportError):
        return HttpResponse(status=404)

    if not custom_list.user_can_view(user):
        return HttpResponse(status=403)

    now = timezone.now()
    days_before = _clamped_int(request.GET.get("days_before"), default=30, lo=0, hi=365)
    days_after = _clamped_int(request.GET.get("days_after"), default=90, lo=0, hi=365)
    start_date = now.date() - timedelta(days=days_before)
    end_date = now.date() + timedelta(days=days_after)

    releases = Event.objects.get_user_events(user, start_date, end_date)
    allowed_item_ids = set(custom_list.items.values_list("pk", flat=True))
    releases = [r for r in releases if r.item_id in allowed_item_ids]

    cal = icalendar.Calendar()
    cal.add("prodid", "-//Yamtrack//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"Yamtrack — {custom_list.name}")

    for release in releases:
        cal_event = icalendar.Event()
        cal_event.add("uid", release.id)
        cal_event.add("summary", str(release))
        dt_tz_aware = release.datetime.replace(tzinfo=UTC)
        cal_event.add("dtstart", dt_tz_aware)
        cal_event.add("dtend", dt_tz_aware)
        cal_event.add("dtstamp", now)
        cal.add_component(cal_event)

    response = HttpResponse(cal.to_ical(), content_type="text/calendar")
    response["Content-Disposition"] = (
        f'attachment; filename="yamtrack-list-{list_id}.ics"'
    )
    return response
