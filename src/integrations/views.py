"""Contains views for importing and exporting media data from various sources."""

import json
import logging
import secrets
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, Max
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import users
from app import helpers as app_helpers
from app.models import MediaTypes, Status
from integrations import exports, hardcover_client, scrobble, tasks
from integrations.hardcover_client import HardcoverAPIError, HardcoverAuthError
from integrations.imports import anilist, discogs, hardcover, helpers, simkl, trakt
from integrations.imports.helpers import MediaImportError
from integrations.koreader import _apply_progress_to_book
from integrations.models import (
    HardcoverIntegration,
    KOReaderBookMapping,
    KOReaderProgressEvent,
    WebhookEvent,
)
from integrations.webhooks import emby, jellyfin, plex

logger = logging.getLogger(__name__)


def _record_webhook(*, user, source, ok, status_code, payload=None, error=""):
    """Best-effort write of a WebhookEvent row.

    The webhook handler must keep working even if logging the event fails
    (e.g. table missing during a partial deploy), so swallow exceptions
    and just warn.
    """
    try:
        if isinstance(payload, (bytes, bytearray)):
            sample = payload.decode("utf-8", errors="replace")[:2000]
        elif isinstance(payload, str):
            sample = payload[:2000]
        elif payload is not None:
            sample = json.dumps(payload, default=str)[:2000]
        else:
            sample = ""

        title = ""
        if isinstance(payload, dict):
            for key in ("Name", "title", "ItemName"):
                value = payload.get(key)
                if value:
                    title = str(value)
                    break

        WebhookEvent.record(
            user=user,
            source=source,
            ok=ok,
            status_code=status_code,
            title=title,
            error=str(error),
            payload_sample=sample,
        )
    except Exception:
        logger.exception("Failed to record WebhookEvent (source=%s)", source)


@require_POST
def trakt_oauth(request):
    """View for initiating Trakt OAuth2 authorization flow."""
    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_trakt_private"),
    )
    url = "https://trakt.tv/oauth/authorize"
    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
        "redirect_uri": redirect_uri,
    }
    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state
    return redirect(
        f"{url}?{
            urlencode(
                {
                    'client_id': settings.TRAKT_API,
                    'redirect_uri': redirect_uri,
                    'response_type': 'code',
                    'state': state_token,
                }
            )
        }",
    )


@require_GET
def import_trakt_private(request):
    """View for handling Trakt OAuth2 callback and scheduling private import."""
    state_token = request.GET.get("state")
    state = request.session.get(state_token)
    if not state:
        messages.error(request, "Invalid or expired Trakt authorization request.")
        return redirect("import_data")

    if not request.GET.get("code"):
        messages.error(request, "Trakt authorization failed.")
        return redirect("import_data")

    redirect_uri = state.get("redirect_uri") or app_helpers.build_absolute_app_url(
        request,
        reverse("import_trakt_private"),
    )
    oauth_callback = trakt.handle_oauth_callback(request, redirect_uri=redirect_uri)
    enc_token = helpers.encrypt(oauth_callback["refresh_token"])

    frequency = state["frequency"]
    mode = state["mode"]
    import_time = state["time"]

    if frequency == "once":
        tasks.import_trakt.delay(
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
            username=oauth_callback["username"],
            redirect_uri=redirect_uri,
        )
        messages.info(request, "The task to import media from Trakt has been queued.")
    else:
        helpers.create_import_schedule(
            oauth_callback["username"],
            request,
            mode,
            frequency,
            import_time,
            "Trakt",
            token=enc_token,
            task_kwargs={"redirect_uri": redirect_uri},
        )
    request.session.pop(state_token, None)
    return redirect("import_data")


@require_POST
def import_trakt_public(request):
    """View for importing Trakt data using public username."""
    username = request.POST.get("user")
    if not username:
        messages.error(request, "Trakt username is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]

    if frequency == "once":
        tasks.import_trakt.delay(
            user_id=request.user.id,
            mode=mode,
            username=username,
        )
        messages.info(request, "The task to import media from Trakt has been queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="Trakt",
        )
    return redirect("import_data")


@require_POST
def simkl_oauth(request):
    """View for initiating the SIMKL OAuth2 authorization flow."""
    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_simkl_private"),
    )
    url = "https://simkl.com/oauth/authorize"

    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
    }
    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state

    return redirect(
        f"{url}?{
            urlencode(
                {
                    'client_id': settings.SIMKL_ID,
                    'redirect_uri': redirect_uri,
                    'response_type': 'code',
                    'state': state_token,
                }
            )
        }",
    )


@require_GET
def import_simkl_private(request):
    """View for getting the SIMKL OAuth2 token."""
    oauth_callback = simkl.get_token(request)
    enc_token = helpers.encrypt(oauth_callback["access_token"])
    state_token = request.GET["state"]

    frequency = request.session[state_token]["frequency"]
    mode = request.session[state_token]["mode"]
    import_time = request.session[state_token]["time"]

    if frequency == "once":
        tasks.import_simkl.delay(token=enc_token, user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from Simkl has been queued.")
    else:
        helpers.create_import_schedule(
            oauth_callback["username"],
            request,
            mode,
            frequency,
            import_time,
            "SIMKL",
            token=enc_token,
        )

    return redirect("import_data")


@require_POST
def import_mal(request):
    """View for importing anime and manga data from MyAnimeList."""
    username = request.POST.get("user")
    if not username:
        messages.error(request, "MyAnimeList username is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_mal.delay(username=username, user_id=request.user.id, mode=mode)
        messages.info(
            request,
            "The task to import media from MyAnimeList has been queued.",
        )
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            username,
            request,
            mode,
            frequency,
            import_time,
            "MyAnimeList",
        )
    return redirect("import_data")


@require_POST
def anilist_oauth(request):
    """Initiate AniList OAuth flow."""
    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_anilist_private"),
    )
    url = "https://anilist.co/api/v2/oauth/authorize"
    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
    }

    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state

    return redirect(
        f"{url}?{
            urlencode(
                {
                    'client_id': settings.ANILIST_ID,
                    'redirect_uri': redirect_uri,
                    'response_type': 'code',
                    'state': state_token,
                }
            )
        }",
    )


@require_GET
def import_anilist_private(request):
    """View for getting the AniList OAuth2 token."""
    oauth_callback = anilist.get_token(request)
    enc_token = helpers.encrypt(oauth_callback["access_token"])
    state_token = request.GET["state"]
    username = oauth_callback["username"]

    if not username:
        messages.error(request, "AniList username is required.")
        return redirect("import_data")

    frequency = request.session[state_token]["frequency"]
    mode = request.session[state_token]["mode"]
    import_time = request.session[state_token]["time"]

    if frequency == "once":
        tasks.import_anilist.delay(
            user_id=request.user.id,
            mode=mode,
            username=username,
            token=enc_token,
        )
        messages.info(request, "AniList import queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="AniList",
            token=enc_token,
        )
    return redirect("import_data")


@require_POST
def import_anilist_public(request):
    """View for importing anime and manga data from AniList."""
    username = request.POST.get("user")
    if not username:
        messages.error(request, "AniList username is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]

    if frequency == "once":
        tasks.import_anilist.delay(
            user_id=request.user.id,
            mode=mode,
            username=username,
        )
        messages.info(request, "AniList import queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="AniList",
        )
    return redirect("import_data")


@require_POST
def import_kitsu(request):
    """View for importing anime and manga data from Kitsu by user ID."""
    kitsu_id = request.POST.get("user")
    if not kitsu_id:
        messages.error(request, "Kitsu user ID is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_kitsu.delay(username=kitsu_id, user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from Kitsu has been queued.")
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            kitsu_id,
            request,
            mode,
            frequency,
            import_time,
            "Kitsu",
        )
    return redirect("import_data")


@require_POST
def import_yamtrack(request):
    """View for importing anime and manga data from Yamtrack CSV."""
    file = request.FILES.get("yamtrack_csv")

    if not file:
        messages.error(request, "Yamtrack CSV file is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    tasks.import_yamtrack.delay(
        file=request.FILES["yamtrack_csv"],
        user_id=request.user.id,
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from Yamtrack CSV file has been queued.",
    )
    return redirect("import_data")


@require_POST
def import_hltb(request):
    """View for importing game date from HowLongToBeat."""
    file = request.FILES.get("hltb_csv")

    if not file:
        messages.error(request, "HowLongToBeat CSV file is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    tasks.import_hltb.delay(
        file=request.FILES["hltb_csv"],
        user_id=request.user.id,
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from HowLongToBeat CSV file has been queued.",
    )
    return redirect("import_data")


@require_POST
def import_steam(request):
    """View for importing game data from Steam."""
    steam_id = (request.POST.get("user") or "").strip()
    if not steam_id:
        messages.error(request, "Steam ID is required.")
        return redirect("import_data")

    # A valid SteamID64 is a 17-digit numeric string (starts with 7656). A
    # common mistake is pasting the Steam API key (32-char hex) into this
    # field; catch that with a clear message instead of letting the importer
    # explode mid-task with a confusing 400 from the Steam API.
    if not (steam_id.isdigit() and len(steam_id) == 17):  # noqa: PLR2004 — SteamID64 length
        messages.error(
            request,
            "That doesn't look like a SteamID64. Expected a 17-digit number "
            "(e.g. 76561198xxxxxxxxx). If you pasted your Steam API key, "
            "use the numeric ID from your profile page instead.",
        )
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_steam.delay(username=steam_id, user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from Steam has been queued.")
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            steam_id,
            request,
            mode,
            frequency,
            import_time,
            "Steam",
        )
    return redirect("import_data")


def import_imdb(request):
    """View for importing data from IMDB."""
    file = request.FILES.get("imdb_csv")

    if not file:
        messages.error(request, "IMDB CSV file is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    tasks.import_imdb.delay(
        file=request.FILES["imdb_csv"],
        user_id=request.user.id,
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from IMDB CSV file has been queued.",
    )
    return redirect("import_data")


@require_POST
def import_goodreads(request):
    """View for importing books data from GoodReads CSV."""
    file = request.FILES.get("goodreads_csv")

    if not file:
        messages.error(request, "GoodReads CSV file is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    tasks.import_goodreads.delay(
        file=request.FILES["goodreads_csv"],
        user_id=request.user.id,
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from GoodReads CSV file has been queued.",
    )
    return redirect("import_data")


@require_POST
def import_hardcover(request):
    """View for importing books from Hardcover via API token."""
    token = (request.POST.get("token") or "").strip()
    if not token:
        messages.error(request, "Hardcover API token is required.")
        return redirect("import_data")

    try:
        username = hardcover.get_username(token)
    except MediaImportError as error:
        messages.error(request, str(error))
        return redirect("import_data")

    enc_token = helpers.encrypt(token)
    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_hardcover.delay(
            user_id=request.user.id,
            mode=mode,
            token=enc_token,
            username=username,
        )
        messages.info(
            request,
            "The task to import books from Hardcover has been queued.",
        )
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="Hardcover",
            token=enc_token,
        )
    return redirect("import_data")


@require_POST
def import_discogs(request):
    """View for importing vinyl records from Discogs via API token."""
    token = (request.POST.get("token") or "").strip()
    if not token:
        messages.error(request, "Discogs API token is required.")
        return redirect("import_data")

    try:
        username = discogs.get_username(token)
    except MediaImportError as error:
        messages.error(request, str(error))
        return redirect("import_data")

    enc_token = helpers.encrypt(token)
    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_discogs.delay(
            user_id=request.user.id,
            mode=mode,
            token=enc_token,
            username=username,
        )
        messages.info(
            request,
            "The task to import vinyl from Discogs has been queued.",
        )
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="Discogs",
            token=enc_token,
        )
    return redirect("import_data")


@require_POST
def import_scrobbles(request):
    """View for importing scrobble history from a generic CSV.

    Expects columns ``played_at, artist, track`` (and an optional
    ``album``). One Play row is created per CSV row, matched to a Record
    by case-insensitive (artist, title) the same way live ListenBrainz
    scrobbles are.
    """
    file = request.FILES.get("scrobbles_csv")
    if not file:
        messages.error(request, "Scrobble CSV file is required.")
        return redirect("import_data")

    mode = request.POST.get("mode", "new")
    tasks.import_scrobbles.delay(
        file=file,
        user_id=request.user.id,
        mode=mode,
    )
    messages.info(
        request,
        "The task to import scrobbles has been queued.",
    )
    return redirect("import_data")


@require_GET
def export_csv(request):
    """View for exporting all media data to a CSV file."""
    now = timezone.localtime()
    response = StreamingHttpResponse(
        streaming_content=exports.generate_rows(request.user),
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="yamtrack_{now}.csv"'},
    )
    logger.info("User %s started CSV export", request.user.username)
    return response


@login_not_required
@csrf_exempt
@require_POST
def jellyfin_webhook(request, token):
    """Handle Jellyfin webhook notifications for media playback."""
    source = WebhookEvent.Source.JELLYFIN
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Jellyfin webhook: Invalid token: %s",
            token,
        )
        _record_webhook(
            user=None, source=source, ok=False, status_code=401, error="Invalid token"
        )
        return HttpResponse(status=401)

    # Attach User instance so history_user_id is populated
    request.user = user
    data = request.body
    if not data:
        logger.warning("Missing payload in Jellyfin webhook request")
        _record_webhook(
            user=user, source=source, ok=False, status_code=400, error="Missing payload"
        )
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
        processor = jellyfin.JellyfinWebhookProcessor()
        processor.process_payload(payload, user)
    except Exception as exc:
        logger.exception("Jellyfin webhook processing failed")
        _record_webhook(
            user=user, source=source, ok=False, status_code=500, payload=data, error=exc
        )
        return HttpResponse(status=500)

    _record_webhook(user=user, source=source, ok=True, status_code=200, payload=payload)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def plex_webhook(request, token):
    """Handle Plex webhook notifications for media playback."""
    source = WebhookEvent.Source.PLEX
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Plex webhook: Invalid token: %s",
            token,
        )
        _record_webhook(
            user=None, source=source, ok=False, status_code=401, error="Invalid token"
        )
        return HttpResponse(status=401)

    # Attach User instance so history_user_id is populated
    request.user = user

    # https://support.plex.tv/hc/en-us/articles/115002267687-Webhooks
    # As stated above, the payload is sent in JSON format inside a multipart
    # HTTP POST request. For the media.play and media.rate events, a second part of
    # the POST request contains a JPEG thumbnail for the media.

    data = request.POST.get("payload")
    if not data:
        logger.warning("Missing payload in Plex webhook request")
        _record_webhook(
            user=user, source=source, ok=False, status_code=400, error="Missing payload"
        )
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
        processor = plex.PlexWebhookProcessor()
        processor.process_payload(payload, user)
    except Exception as exc:
        logger.exception("Plex webhook processing failed")
        _record_webhook(
            user=user, source=source, ok=False, status_code=500, payload=data, error=exc
        )
        return HttpResponse(status=500)

    _record_webhook(user=user, source=source, ok=True, status_code=200, payload=payload)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_GET
def listenbrainz_validate_token(request):
    """ListenBrainz-compatible token validation endpoint.

    Multi-scrobbler hits this on first connect to verify the destination is
    reachable. Token comes via ``Authorization: Token <user-token>``.
    """
    token = scrobble.extract_bearer_token(request)
    if not token:
        return HttpResponse(
            json.dumps(
                {
                    "code": 401,
                    "message": "Missing or malformed Authorization header.",
                    "valid": False,
                },
            ),
            status=401,
            content_type="application/json",
        )
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        return HttpResponse(
            json.dumps(
                {"code": 401, "message": "Invalid token.", "valid": False},
            ),
            status=200,
            content_type="application/json",
        )
    return HttpResponse(
        json.dumps(
            {
                "code": 200,
                "message": "Token valid.",
                "valid": True,
                "user_name": user.username,
            },
        ),
        status=200,
        content_type="application/json",
    )


@login_not_required
@csrf_exempt
@require_GET
def listenbrainz_get_listens(request, user_name):
    """ListenBrainz-compatible ``GET /1/user/<user_name>/listens``.

    Multi-scrobbler calls this before submitting, to deduplicate against
    listens the server already has. Without it the GET 404s and
    multi-scrobbler aborts the whole scrobble cycle.

    Resolve the user by token if one is supplied (consistent with the
    other endpoints), otherwise fall back to the username in the URL so
    this also works for anonymous reads like real ListenBrainz.
    """
    token = scrobble.extract_bearer_token(request)
    user = None
    if token:
        user = users.models.User.objects.filter(token=token).first()
    if user is None:
        user = users.models.User.objects.filter(username=user_name).first()
    if user is None:
        return HttpResponse(
            json.dumps({"code": 404, "error": "User not found."}),
            status=404,
            content_type="application/json",
        )

    def _int_param(*names):
        for name in names:
            raw = request.GET.get(name)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
        return None

    count = _int_param("count") or scrobble.LISTENS_DEFAULT_COUNT
    payload = scrobble.get_user_listens(
        user,
        min_ts=_int_param("min_ts", "from"),
        max_ts=_int_param("max_ts", "to"),
        count=count,
    )
    return HttpResponse(
        json.dumps({"payload": payload}),
        status=200,
        content_type="application/json",
    )


@login_not_required
@csrf_exempt
@require_POST
def listenbrainz_submit_listens(request):
    """ListenBrainz-compatible scrobble receiver.

    Multi-scrobbler / clients POST a JSON body of one or more listens here.
    Each listen turns into a ``Play`` row, with ``Item`` resolution by
    case-insensitive ``(artist, title)`` match.
    """
    token = scrobble.extract_bearer_token(request)
    if not token:
        return HttpResponse(
            json.dumps(
                {"code": 401, "error": "Missing Authorization header."},
            ),
            status=401,
            content_type="application/json",
        )
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        return HttpResponse(
            json.dumps({"code": 401, "error": "Invalid token."}),
            status=401,
            content_type="application/json",
        )

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponse(
            json.dumps({"code": 400, "error": "Body is not valid JSON."}),
            status=400,
            content_type="application/json",
        )

    try:
        scrobble.submit_listens(user, body)
    except ValueError as error:
        return HttpResponse(
            json.dumps({"code": 400, "error": str(error)}),
            status=400,
            content_type="application/json",
        )

    return HttpResponse(
        json.dumps({"status": "ok"}),
        status=200,
        content_type="application/json",
    )


@login_not_required
@csrf_exempt
@require_POST
def emby_webhook(request, token):
    """Handle Emby webhook notifications for media playback."""
    source = WebhookEvent.Source.EMBY
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Emby webhook: Invalid token: %s",
            token,
        )
        _record_webhook(
            user=None, source=source, ok=False, status_code=401, error="Invalid token"
        )
        return HttpResponse(status=401)

    # Attach User instance so history_user_id is populated
    request.user = user

    # The payload is sent in JSON format inside a multipart
    # HTTP POST request.

    data = request.POST.get("data")
    if not data:
        logger.warning("Missing payload in Emby webhook request")
        _record_webhook(
            user=user, source=source, ok=False, status_code=400, error="Missing payload"
        )
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
        processor = emby.EmbyWebhookProcessor()
        processor.process_payload(payload, user)
    except Exception as exc:
        logger.exception("Emby webhook processing failed")
        _record_webhook(
            user=user, source=source, ok=False, status_code=500, payload=data, error=exc
        )
        return HttpResponse(status=500)

    _record_webhook(user=user, source=source, ok=True, status_code=200, payload=payload)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def quick_log(request, token):  # noqa: C901, PLR0912 — multi-path response handler
    """Token-authenticated quick-log endpoint for Shortcuts / Tasker / bots.

    POST body (JSON or form-encoded):
        ``title``        — required, fuzzy-matched against the user's library
        ``media_type``   — optional, narrows the search to one MediaTypes value

    Responses:
        200 + ``{"action": "advanced", "title": ..., "media_type": ...}``
            Exactly one match — progress incremented (or status flipped to
            Completed for movies/games that have no progress field).
        300 + ``{"candidates": [{"id", "title", "media_type"}, ...]}``
            Multiple matches — caller picks one and resubmits with a
            ``media_type`` filter.
        404 + ``{"error": "no_match"}``
            No library item matched; the caller should fall back to /search.
    """
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        return JsonResponse({"error": "invalid_token"}, status=401)

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid_json"}, status=400)
    else:
        payload = request.POST

    title = (payload.get("title") or "").strip()
    requested_type = (payload.get("media_type") or "").strip()
    if not title:
        return JsonResponse({"error": "missing_title"}, status=400)

    types_to_search = (
        [requested_type]
        if requested_type
        else [
            media_type
            for media_type in MediaTypes.values
            if media_type not in (MediaTypes.EPISODE.value, MediaTypes.SEASON.value)
        ]
    )

    matches = []
    for media_type in types_to_search:
        try:
            model = apps.get_model("app", media_type)
        except LookupError:
            continue
        qs = model.objects.filter(
            user=user, item__title__icontains=title
        ).select_related("item")[:5]
        matches.extend((media_type, media) for media in qs)

    if not matches:
        return JsonResponse({"error": "no_match", "query": title}, status=404)

    if len(matches) > 1:
        return JsonResponse(
            {
                "candidates": [
                    {"id": m.pk, "title": m.item.title, "media_type": mt}
                    for mt, m in matches
                ],
            },
            status=300,
        )

    media_type, media = matches[0]
    request.user = user  # for simple_history attribution
    field_names = {f.name for f in media._meta.fields}
    update_fields = []
    action = "noop"

    if "progress" in field_names and getattr(media, "progress", None) is not None:
        media.progress = (media.progress or 0) + 1
        update_fields.append("progress")
        action = "advanced"
    if "status" in field_names and media.status != Status.COMPLETED.value:
        if "progress" in field_names:
            media.status = Status.IN_PROGRESS.value
            action = "advanced"
        else:
            media.status = Status.COMPLETED.value
            action = "completed"
        update_fields.append("status")

    if update_fields:
        media.save(update_fields=update_fields)

    return JsonResponse(
        {
            "action": action,
            "title": media.item.title,
            "media_type": media_type,
            "id": media.pk,
        },
    )


@require_POST
def hardcover_connect(request):
    """Connect (or update) a Hardcover account by API token.

    Token is validated against ``me { id username }`` before being
    encrypted-at-rest. An existing integration row is updated in place so
    users can rotate their annual-reset token without losing their cached
    book mappings.
    """
    token = (request.POST.get("token") or "").strip()
    if not token:
        messages.error(request, "Hardcover API token is required.")
        return redirect("integrations")

    try:
        hc_user_id, hc_username = hardcover_client.get_me(token)
    except (HardcoverAuthError, HardcoverAPIError) as error:
        messages.error(request, str(error))
        return redirect("integrations")

    enc_token = helpers.encrypt(token)
    HardcoverIntegration.objects.update_or_create(
        user=request.user,
        defaults={
            "api_token": enc_token,
            "hardcover_user_id": hc_user_id,
            "hardcover_username": hc_username,
            "enabled": True,
            "last_error": "",
            "last_error_at": None,
        },
    )
    messages.success(
        request,
        f"Connected to Hardcover as @{hc_username}. Book progress will sync on save.",
    )
    return redirect("integrations")


@require_POST
def koreader_link(request):
    """Bind an unmapped KOReader document hash to a Book ``Item``.

    Reached from the integrations settings page. After binding, the
    last-known percentage stored on the mapping row is replayed onto
    the Book so the user doesn't have to wait for the next KOReader
    sync to see the catch-up.
    """
    document = (request.POST.get("document_hash") or "").strip().lower()
    item_id = (request.POST.get("item_id") or "").strip()
    if not document or not item_id:
        messages.error(request, "Pick a book to link.")
        return redirect("integrations")

    mapping = KOReaderBookMapping.objects.filter(
        user=request.user,
        document_hash=document,
    ).first()
    if mapping is None:
        messages.error(request, "Unknown KOReader document hash.")
        return redirect("integrations")

    item_model = apps.get_model("app", "Item")
    try:
        item = item_model.objects.get(pk=item_id, media_type="book")
    except ObjectDoesNotExist:
        messages.error(request, "Book not found in your library.")
        return redirect("integrations")

    mapping.item = item
    mapping.save(update_fields=["item"])

    if mapping.last_progress_at is not None and mapping.last_percentage > 0:
        try:
            _apply_progress_to_book(request.user, item, mapping.last_percentage)
        except Exception:
            logger.exception("Replaying KOReader progress after bind failed")
            messages.warning(
                request,
                f"Linked, but couldn't replay progress onto {item.title}.",
            )
        else:
            messages.success(request, f"Linked KOReader sync to {item.title}.")
            return redirect("integrations")

    messages.success(request, f"Linked KOReader sync to {item.title}.")
    return redirect("integrations")


@require_POST
def koreader_unlink(request):
    """Drop a KOReader document mapping for the current user."""
    document = (request.POST.get("document_hash") or "").strip().lower()
    deleted, _ = KOReaderBookMapping.objects.filter(
        user=request.user,
        document_hash=document,
    ).delete()
    if deleted:
        messages.info(request, "KOReader mapping removed.")
    return redirect("integrations")


@require_GET
def koreader_book_history(request, book_pk):
    """Per-book reading-history view, sourced from the kosync event log.

    The ``KOReaderBookMapping`` row only carries the latest state, so the
    actual timeline lives in ``KOReaderProgressEvent``. We group events
    by device for Chart.js so each device renders as its own dataset
    (own colour, own legend entry, hover tooltips per point). If the
    user has more than one mapping bound to the same Item (e.g. they
    re-downloaded a different epub edition), events from all of them
    appear on the same chart in chronological order.
    """
    book_model = apps.get_model("app", "book")
    book = get_object_or_404(book_model, pk=book_pk, user=request.user)

    events = list(
        KOReaderProgressEvent.objects.filter(
            user=request.user,
            mapping__item=book.item,
        )
        .order_by("created_at")
        .values("created_at", "percentage", "progress", "device", "device_id"),
    )

    by_device = {}
    for ev in events:
        key = ev["device_id"] or ev["device"] or "unknown"
        label = ev["device"] or ev["device_id"] or "Unknown device"
        bucket = by_device.setdefault(key, {"label": label, "points": []})
        bucket["points"].append(
            {
                # Epoch ms keeps Chart.js on the linear axis (no
                # chartjs-adapter-date-fns dependency to ship).
                "x": int(ev["created_at"].timestamp() * 1000),
                "y": round(ev["percentage"] * 100, 2),
                "page": ev["progress"],
            },
        )

    datasets = list(by_device.values())

    return render(
        request,
        "integrations/koreader_book_history.html",
        {
            "book": book,
            "datasets_json": json.dumps(datasets),
            "event_count": len(events),
            "device_count": len(datasets),
        },
    )


@require_GET
def koreader_devices(request):
    """Cross-book device summary: every KOReader device this user has used.

    Aggregates the event log per ``(device, device_id)`` pair so the
    template can show one row per physical device — last seen, total
    sync count, distinct books touched, and the most-recently-synced
    book (resolved via a per-row follow-up query, N is tiny - most
    users have 1-3 devices).
    """
    devices = list(
        KOReaderProgressEvent.objects.filter(user=request.user)
        .values("device", "device_id")
        .annotate(
            last_seen=Max("created_at"),
            event_count=Count("id"),
            book_count=Count("mapping__item", distinct=True),
        )
        .order_by("-last_seen"),
    )

    for device in devices:
        last_event = (
            KOReaderProgressEvent.objects.filter(
                user=request.user,
                device=device["device"],
                device_id=device["device_id"],
            )
            .select_related("mapping__item")
            .order_by("-created_at")
            .first()
        )
        last_item = (
            last_event.mapping.item
            if last_event and last_event.mapping_id and last_event.mapping.item_id
            else None
        )
        device["last_item"] = last_item

    return render(
        request,
        "integrations/koreader_devices.html",
        {"devices": devices},
    )


@require_POST
def hardcover_disconnect(request):
    """Disconnect the current user's Hardcover integration.

    Cached ``HardcoverBookMapping`` rows are intentionally kept — they're
    keyed on Item, not the integration, and would just need to be
    re-resolved on a future reconnect. No reason to throw them away.
    """
    HardcoverIntegration.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected from Hardcover. No more progress will sync.")
    return redirect("integrations")
