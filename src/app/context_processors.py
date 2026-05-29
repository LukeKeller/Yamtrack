# https://docs.djangoproject.com/en/stable/ref/templates/api/#writing-your-own-context-processors

from django.conf import settings

from app.models import MediaTypes, Sources, Status, UserMessage
from app.release_notes import CURRENT_FORK_VERSION, entries_since


def export_vars(request):  # noqa: ARG001
    """Export variables to templates."""
    from users.models import EinkChoices  # noqa: PLC0415 — avoid import cycle

    return {
        "REGISTRATION": settings.REGISTRATION,
        "REDIRECT_LOGIN_TO_SSO": settings.REDIRECT_LOGIN_TO_SSO,
        "IMG_NONE": settings.IMG_NONE,
        "TRACK_TIME": settings.TRACK_TIME,
        "FORK_VERSION": CURRENT_FORK_VERSION,
        # Drives the header quick-toggle in base.html (off / auto / on).
        "eink_choices": EinkChoices.choices,
    }


def media_enums(request):  # noqa: ARG001
    """Export media enums to templates."""
    return {
        "MediaTypes": MediaTypes,
        "Sources": Sources,
        "Status": Status,
    }


def persistent_messages(request):
    """Return persistent user notifications that have not been shown yet."""
    if not request.user.is_authenticated:
        return {"persistent_messages": []}

    return {
        "persistent_messages": list(
            UserMessage.objects.filter(
                user=request.user,
                shown_at__isnull=True,
            ),
        ),
    }


def whats_new(request):
    """Surface unread release-note entries for the What's New modal.

    Skips htmx-targeted requests (the modal should only appear on full page
    loads), unauthenticated users, and users already current on the latest
    release.
    """
    if not request.user.is_authenticated:
        return {}

    if request.headers.get("HX-Request") == "true":
        return {}

    user_version = request.user.last_seen_version
    if user_version == CURRENT_FORK_VERSION:
        return {}

    entries = entries_since(user_version)
    if not entries:
        return {}

    return {
        "whats_new_entries": entries,
        "whats_new_current_version": CURRENT_FORK_VERSION,
    }
