"""Per-user timezone activation.

Django's TIME_ZONE setting is project-wide, but each user can have a different
preferred zone (e.g. America/New_York vs Europe/London). This middleware
activates ``request.user.timezone`` for the lifetime of the request so every
template tag and view that calls ``timezone.localtime`` / ``localdate`` /
``now`` renders in the right zone. Empty string falls back to the server's
default — no-op for users who haven't set one.
"""

import zoneinfo

from django.utils import timezone


class UserTimezoneMiddleware:
    """Activate request.user.timezone for the duration of the request."""

    def __init__(self, get_response):
        """Cache the get_response callable for the standard middleware contract."""
        self.get_response = get_response

    def __call__(self, request):
        """Activate the request user's timezone, then delegate down the chain."""
        tz_name = ""
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            tz_name = getattr(user, "timezone", "") or ""

        if tz_name:
            try:
                timezone.activate(zoneinfo.ZoneInfo(tz_name))
            except zoneinfo.ZoneInfoNotFoundError:
                timezone.deactivate()
        else:
            timezone.deactivate()

        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
