"""KOReader progress-sync (kosync) endpoint handlers.

KOReader's built-in "Progress sync" plugin talks to a kosync server over
four endpoints. The official server stores its own users and MD5'd
passwords; this implementation reuses the Yamtrack account instead — the
caller's username is their Yamtrack username and the "password"
KOReader sends (MD5 of whatever was typed) is checked against
``md5(user.token)``. That keeps account management on the existing
Yamtrack login and lets the user rotate sync access just by regenerating
their integration token.

Endpoints (all under ``/api/koreader/`` in ``integrations/urls.py``):

* ``POST /users/create`` — registration. Returns 201 if (username,
  md5(token)) matches an existing Yamtrack user; the KOReader plugin
  uses this to validate credentials at setup. 401 otherwise.
* ``GET /users/auth`` — credentials probe used by the plugin's
  "Connect" button. Reads the same ``x-auth-user`` / ``x-auth-key``
  headers that every subsequent request carries.
* ``PUT /syncs/progress`` — body has ``{document, progress, percentage,
  device, device_id}``. Upserts a ``KOReaderBookMapping`` row keyed on
  (user, document); if the row is bound to an ``Item`` we route the
  percentage into the matching ``Book``'s ``progress`` and ``status``
  via the normal ``Book.save()`` path (so history, ``progressed_at``,
  end-date stamping, and any outbound Hardcover push all fire).
* ``GET /syncs/progress/<document>`` — returns the last row when one
  exists, or ``404 {"status": "not found"}`` otherwise (matches the
  TypeScript reference at nperez0111/koreader-sync; KOReader's client
  only branches on ``status == 200`` and treats 404 as "no remote
  progress, fall back to local").
"""

import hashlib
import json
import logging
import time

from django.apps import apps
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

import users
from app import providers
from app.models import MediaTypes, Status
from integrations.models import KOReaderBookMapping

logger = logging.getLogger(__name__)

# KOReader normalises hashes to lowercase hex; 32 chars exactly.
DOCUMENT_HASH_LEN = 32
# Threshold for flipping a book to Completed on a KOReader push. KOReader
# rarely reports a true 1.0 — readers tap "I finished it" before the EOF
# epubcfi — so we cap a hair below 1.0 to avoid getting stuck at "99%".
COMPLETION_PCT = 0.97


def _md5_hex(value):
    """Return the lowercase hex MD5 of ``value`` (str or bytes)."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def _authenticate(request):
    """Resolve (User, error_response) from kosync auth headers.

    Returns ``(user, None)`` on success or ``(None, JsonResponse)`` with
    the response the caller should return on failure. KOReader always
    sends both headers and they're cheap to validate, so we do it
    eagerly at the top of every endpoint.
    """
    username = request.headers.get("x-auth-user", "").strip()
    auth_key = request.headers.get("x-auth-key", "").strip().lower()
    if not username or not auth_key:
        return None, JsonResponse(
            {"code": 401, "message": "Missing credentials."},
            status=401,
        )

    try:
        user = users.models.User.objects.get(username=username)
    except ObjectDoesNotExist:
        return None, JsonResponse(
            {"code": 2001, "message": "Unauthorized user."},
            status=401,
        )

    if _md5_hex(user.token) != auth_key:
        return None, JsonResponse(
            {"code": 2001, "message": "Unauthorized user."},
            status=401,
        )

    return user, None


def _parse_body(request):
    """Return parsed JSON body or empty dict; never raises."""
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None


@login_not_required
@csrf_exempt
@require_POST
def users_create(request):
    """Validate credentials and confirm setup.

    Yamtrack accounts already exist outside the kosync world, so this
    endpoint never actually creates anything — it just answers
    "are these credentials usable?". A successful response is shaped
    exactly like the reference kosync server (``{"username": "..."}``,
    201) so the KOReader plugin treats setup as complete.
    """
    payload = _parse_body(request)
    if payload is None:
        return JsonResponse({"code": 400, "message": "Invalid JSON."}, status=400)

    username = (payload.get("username") or "").strip()
    password = (payload.get("password") or "").strip().lower()
    if not username or not password:
        return JsonResponse(
            {"code": 400, "message": "Username and password required."},
            status=400,
        )

    try:
        user = users.models.User.objects.get(username=username)
    except ObjectDoesNotExist:
        return JsonResponse(
            {"code": 2001, "message": "Unauthorized user."},
            status=401,
        )

    if _md5_hex(user.token) != password:
        return JsonResponse(
            {"code": 2001, "message": "Unauthorized user."},
            status=401,
        )

    return JsonResponse({"username": user.username}, status=201)


@login_not_required
@csrf_exempt
@require_GET
def users_auth(request):
    """Credential probe — answers KOReader's "Connect" button."""
    _user, error = _authenticate(request)
    if error is not None:
        return error
    return JsonResponse({"authorized": "OK"})


@login_not_required
@csrf_exempt
@require_http_methods(["PUT"])
def progress_put(request):
    """Accept a progress update and route it onto the linked Book.

    Unknown document hashes don't error — they create an unbound
    ``KOReaderBookMapping`` so the user can link it later in the
    integrations UI. The raw percentage is preserved on the mapping
    row so a delayed bind can replay it.
    """
    user, error = _authenticate(request)
    if error is not None:
        return error

    payload = _parse_body(request)
    if payload is None:
        return JsonResponse({"code": 400, "message": "Invalid JSON."}, status=400)

    document = (payload.get("document") or "").strip().lower()
    if len(document) != DOCUMENT_HASH_LEN or not all(
        c in "0123456789abcdef" for c in document
    ):
        return JsonResponse(
            {"code": 400, "message": "Invalid document hash."},
            status=400,
        )

    try:
        percentage = float(payload.get("percentage", 0.0))
    except (TypeError, ValueError):
        return JsonResponse(
            {"code": 400, "message": "Invalid percentage."},
            status=400,
        )
    percentage = max(0.0, min(1.0, percentage))

    progress_str = str(payload.get("progress") or "")[:2000]
    device = str(payload.get("device") or "")[:255]
    device_id = str(payload.get("device_id") or "")[:64]

    now = timezone.now()
    mapping, _ = KOReaderBookMapping.objects.update_or_create(
        user=user,
        document_hash=document,
        defaults={
            "last_progress": progress_str,
            "last_percentage": percentage,
            "last_device": device,
            "last_device_id": device_id,
            "last_progress_at": now,
        },
    )

    if mapping.item_id is not None:
        try:
            _apply_progress_to_book(user, mapping.item, percentage)
        except Exception:
            # The kosync response shouldn't depend on the Book write
            # succeeding (e.g., provider lookup hiccup) — KOReader will
            # retry on next page turn and we can replay on bind.
            logger.exception(
                "Failed to apply KOReader progress to Book (user=%s item=%s)",
                user.pk,
                mapping.item_id,
            )

    return JsonResponse(
        {"document": document, "timestamp": int(time.mktime(now.timetuple()))},
    )


@login_not_required
@csrf_exempt
@require_GET
def progress_get(request, document):
    """Return the last stored progress for ``document``.

    When no row exists we still answer 200 with an empty payload —
    KOReader's plugin treats a 200 with no document field as "nothing
    on the server yet" and skips its overwrite prompt.
    """
    user, error = _authenticate(request)
    if error is not None:
        return error

    document = (document or "").strip().lower()
    mapping = KOReaderBookMapping.objects.filter(
        user=user,
        document_hash=document,
    ).first()
    if mapping is None or mapping.last_progress_at is None:
        return JsonResponse({"status": "not found"}, status=404)

    return JsonResponse(
        {
            "document": mapping.document_hash,
            "progress": mapping.last_progress,
            "percentage": mapping.last_percentage,
            "device": mapping.last_device,
            "device_id": mapping.last_device_id,
            "timestamp": int(time.mktime(mapping.last_progress_at.timetuple())),
        },
    )


def _apply_progress_to_book(user, item, percentage):
    """Translate a kosync percentage onto a tracked ``Book`` row.

    Yamtrack stores book progress as a page count, so we ask the
    provider for the book's total pages and round. If the provider
    doesn't expose a page count (some OpenLibrary editions don't), we
    fall back to status updates only — the percentage is still kept on
    the mapping row for the UI.

    The write goes through ``Book.save()`` rather than a queryset
    ``.update()`` so ``progressed_at`` ticks, the simple_history audit
    trail records the change, and any outbound Hardcover push fires.
    """
    book_model = apps.get_model("app", MediaTypes.BOOK.value)
    book, _ = book_model.objects.get_or_create(
        user=user,
        item=item,
        defaults={"status": Status.PLANNING.value, "progress": 0},
    )

    metadata = providers.services.get_media_metadata(
        item.media_type,
        item.media_id,
        item.source,
    )
    max_progress = metadata.get("max_progress") if metadata else None

    if percentage >= COMPLETION_PCT:
        book.status = Status.COMPLETED.value
        if max_progress:
            book.progress = max_progress
    elif percentage > 0:
        if book.status in (Status.PLANNING.value, Status.PAUSED.value):
            book.status = Status.IN_PROGRESS.value
        if max_progress:
            book.progress = max(book.progress, round(percentage * max_progress))
    # percentage == 0 means "open but not yet read past page 0"; don't
    # downgrade progress or status on those pings.

    book.save()
