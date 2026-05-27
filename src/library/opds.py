"""OPDS 1.2 catalog + acquisition feeds for the library.

KOReader's "Add OPDS catalog" form sends HTTP Basic credentials; we map
the username to the Yamtrack username and the password to the user's
raw integration token (``User.token``), the same token used to mint the
kosync ``x-auth-key`` header (md5-ed) and the Jellyfin/Plex webhook
paths. Using the existing token means OPDS access tracks the rest of
the per-user API surface — regenerating the token revokes everything in
one shot.

Layout: the root at ``/library/opds/`` is a navigation feed listing six
shelves (Up Next / Want to Read / Recently Added / By Author /
Unmatched / All Books), each rendered as its own acquisition feed.
KOReader treats acquisition feeds as browseable lists; download links
carry a typed ``application/epub+zip`` rel. ``/library/opds/file/<pk>``
streams the epub with ``Content-Disposition: attachment;
filename="<canonical>.epub"`` so KOReader saves the file under the
basename we md5'd at upload time. That basename's md5 equals the kosync
``document`` hash KOReader will push on first open → auto-bind on next
sync without ever passing through ``/koreader/unmatched``.

OPDS feeds are XML; we build them by hand with the stdlib's
ElementTree rather than pulling a dedicated library — the schema is
small, the bytes are cheap to test for well-formedness, and adding a
dep just for this would be overkill.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import quote
from xml.etree import ElementTree as ET

from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

import users
from app.models import Book, Status
from library.helpers import stream_iter
from library.models import LibraryFile

logger = logging.getLogger(__name__)

OPDS_NAMESPACE = "http://www.w3.org/2005/Atom"
OPDS_OPDS_NAMESPACE = "http://opds-spec.org/2010/catalog"
DC_NAMESPACE = "http://purl.org/dc/terms/"

NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"

RECENTLY_ADDED_LIMIT = 50

ET.register_namespace("", OPDS_NAMESPACE)
ET.register_namespace("opds", OPDS_OPDS_NAMESPACE)
ET.register_namespace("dcterms", DC_NAMESPACE)


def _basic_auth_user(request):  # noqa: PLR0911 — telemetry-style early returns
    """Decode HTTP Basic; return the Yamtrack user matching token=password.

    Returns ``None`` on any failure — bad header, bad encoding, no user,
    wrong token. The 401 response (with WWW-Authenticate) is the
    caller's responsibility so we don't accidentally swallow real
    errors as auth failures.

    ~ynh135 added telemetry so OPDS auth failures from external clients
    (KOReader's catalog browser specifically) are debuggable without
    leaking the token: we log header presence / length / scheme, and on
    decode-success we log the username + password length, never the
    password itself. The lines are tagged ``OPDS-AUTH:`` so they're easy
    to grep out of the journal once a debug session is over.
    """
    header = request.headers.get("Authorization", "")
    if not header:
        logger.info("OPDS-AUTH: method=%s no Authorization header", request.method)
        return None
    scheme = header.split(" ", 1)[0] if " " in header else header
    if not header.lower().startswith("basic "):
        logger.info(
            "OPDS-AUTH: method=%s non-Basic scheme=%r hdr_len=%d",
            request.method,
            scheme,
            len(header),
        )
        return None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        logger.info(
            "OPDS-AUTH: method=%s base64-decode failed: %s (hdr_len=%d)",
            request.method,
            exc,
            len(header),
        )
        return None
    if ":" not in decoded:
        logger.info(
            "OPDS-AUTH: method=%s no colon in decoded creds (decoded_len=%d)",
            request.method,
            len(decoded),
        )
        return None
    username, _, token = decoded.partition(":")
    if not username or not token:
        logger.info(
            "OPDS-AUTH: method=%s empty username_or_token (u_len=%d t_len=%d)",
            request.method,
            len(username),
            len(token),
        )
        return None
    # Case-insensitive username (matches the kosync convention; KOReader
    # lowercases the OPDS username field for some users too — easier to
    # be permissive than to debug "why does my casing matter only here").
    candidates = list(users.models.User.objects.filter(username__iexact=username))
    if not candidates:
        logger.info(
            "OPDS-AUTH: method=%s username=%r not found (t_len=%d)",
            request.method,
            username,
            len(token),
        )
        return None
    for candidate in candidates:
        if candidate.token == token:
            logger.info(
                "OPDS-AUTH: method=%s username=%r OK user_id=%d",
                request.method,
                username,
                candidate.pk,
            )
            return candidate
    logger.info(
        "OPDS-AUTH: method=%s username=%r token MISMATCH (t_len=%d, expected_len=%d)",
        request.method,
        username,
        len(token),
        len(candidates[0].token or ""),
    )
    return None


def _require_basic_auth(_request):
    """401 with the WWW-Authenticate header KOReader expects."""
    response = HttpResponse(
        b'<?xml version="1.0"?><error>Authentication required.</error>',
        status=401,
        content_type="application/xml",
    )
    response["WWW-Authenticate"] = 'Basic realm="Yamtrack Library"'
    return response


def _shelf_url(request, url_name):
    """Absolute URL for a named shelf endpoint."""
    return request.build_absolute_uri(reverse(url_name))


def _author_url(request, author_name):
    """Absolute URL for the per-author acquisition feed."""
    return _shelf_url(request, "opds_author") + "?a=" + quote(author_name)


def _sub(parent, tag, text=None, *, ns=OPDS_NAMESPACE, **attrs):
    """Append a child element. ``tag`` is local, namespace via kwarg."""
    el = ET.SubElement(parent, f"{{{ns}}}{tag}", attrs)
    if text is not None:
        el.text = text
    return el


def _feed_header(feed, request, user, *, title, self_url, kind):
    """Common id/title/updated/author/self+start links for any feed."""
    root_url = _shelf_url(request, "opds_root")
    self_type = NAV_TYPE if kind == "navigation" else ACQ_TYPE
    _sub(feed, "id", f"yamtrack:library:{user.pk}:{kind}:{title}")
    _sub(feed, "title", title)
    _sub(feed, "updated", timezone.now().isoformat())
    author = _sub(feed, "author")
    _sub(author, "name", "Yamtrack")
    _sub(feed, "link", rel="self", href=self_url, type=self_type)
    _sub(feed, "link", rel="start", href=root_url, type=NAV_TYPE)
    if self_url != root_url:
        _sub(feed, "link", rel="up", href=root_url, type=NAV_TYPE)


def _build_navigation_feed(request, user, *, title, self_url, sections):
    """sections: iterable of (id_slug, label, summary, href, kind)."""
    feed = ET.Element(f"{{{OPDS_NAMESPACE}}}feed")
    _feed_header(feed, request, user, title=title, self_url=self_url, kind="navigation")
    for id_slug, label, summary, href, kind in sections:
        entry = _sub(feed, "entry")
        _sub(entry, "id", f"yamtrack:library:{user.pk}:nav:{id_slug}")
        _sub(entry, "title", label)
        _sub(entry, "updated", timezone.now().isoformat())
        _sub(entry, "content", summary, type="text")
        entry_type = NAV_TYPE if kind == "navigation" else ACQ_TYPE
        _sub(entry, "link", rel="subsection", href=href, type=entry_type)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def _build_acquisition_feed(request, user, files, *, title, self_url):
    """Return the OPDS acquisition feed XML for ``files``."""
    feed = ET.Element(f"{{{OPDS_NAMESPACE}}}feed")
    _feed_header(feed, request, user, title=title, self_url=self_url, kind="acquisition")
    for lf in files:
        entry = _sub(feed, "entry")
        _sub(entry, "id", f"yamtrack:library:{user.pk}:file:{lf.pk}")
        _sub(entry, "title", lf.title or lf.canonical_filename)
        _sub(entry, "updated", (lf.updated_at or lf.created_at).isoformat())
        if lf.author:
            author_el = _sub(entry, "author")
            _sub(author_el, "name", lf.author)
        if lf.language:
            _sub(entry, "language", lf.language, ns=DC_NAMESPACE)
        if lf.isbn_13:
            _sub(entry, "identifier", f"urn:isbn:{lf.isbn_13}", ns=DC_NAMESPACE)
        download_url = request.build_absolute_uri(
            reverse("opds_download", args=[lf.pk]),
        )
        _sub(
            entry,
            "link",
            rel="http://opds-spec.org/acquisition",
            href=download_url,
            type="application/epub+zip",
            title=lf.canonical_filename,
        )
        if lf.cover:
            cover_url = request.build_absolute_uri(lf.cover.url)
            _sub(
                entry,
                "link",
                rel="http://opds-spec.org/image",
                href=cover_url,
                type=_image_mime_for(lf.cover.name),
            )
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def _image_mime_for(filename):
    """Tiny ext→mime mapping for the cover link element."""
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


# ---- Shelf querysets ------------------------------------------------------
#
# Each helper takes a user and returns a LibraryFile queryset. Kept separate
# from the views so the root catalog can call them just to get counts for the
# nav-feed summaries without duplicating the filter logic.


def _files_in_progress(user):
    """LibraryFiles whose linked Book is currently In Progress for this user."""
    item_ids = Book.objects.filter(
        user=user,
        status=Status.IN_PROGRESS.value,
    ).values("item_id")
    return LibraryFile.objects.filter(user=user, item_id__in=item_ids).select_related(
        "item",
    )


def _files_planning(user):
    """LibraryFiles whose linked Book status is Planning for this user."""
    item_ids = Book.objects.filter(
        user=user,
        status=Status.PLANNING.value,
    ).values("item_id")
    return LibraryFile.objects.filter(user=user, item_id__in=item_ids).select_related(
        "item",
    )


def _files_recently_added(user):
    return (
        LibraryFile.objects.filter(user=user)
        .select_related("item")
        .order_by("-created_at")[:RECENTLY_ADDED_LIMIT]
    )


def _files_unmatched(user):
    return LibraryFile.objects.filter(user=user, item__isnull=True).select_related(
        "item",
    )


def _files_all(user):
    return (
        LibraryFile.objects.filter(user=user)
        .select_related("item")
        .order_by("-created_at")
    )


def _files_by_author(user, author):
    return (
        LibraryFile.objects.filter(user=user, author=author)
        .select_related("item")
        .order_by("title")
    )


def _distinct_authors(user):
    return (
        LibraryFile.objects.filter(user=user)
        .exclude(author="")
        .values_list("author", flat=True)
        .distinct()
        .order_by("author")
    )


# ---- Views ----------------------------------------------------------------


def _acquisition_response(request, user, files, *, title, self_url):
    body = _build_acquisition_feed(
        request,
        user,
        files,
        title=title,
        self_url=self_url,
    )
    return HttpResponse(body, content_type=ACQ_TYPE)


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_root(request):
    """Navigation feed listing the six library shelves."""
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)

    in_progress = _files_in_progress(user).count()
    planning = _files_planning(user).count()
    total = LibraryFile.objects.filter(user=user).count()
    unmatched = LibraryFile.objects.filter(user=user, item__isnull=True).count()
    author_count = _distinct_authors(user).count()
    recently_added = min(total, RECENTLY_ADDED_LIMIT)

    sections = [
        (
            "up-next",
            "Up Next",
            f"{in_progress} book(s) currently in progress",
            _shelf_url(request, "opds_up_next"),
            "acquisition",
        ),
        (
            "want-to-read",
            "Want to Read",
            f"{planning} book(s) planned",
            _shelf_url(request, "opds_want_to_read"),
            "acquisition",
        ),
        (
            "recently-added",
            "Recently Added",
            f"{recently_added} most recent upload(s)",
            _shelf_url(request, "opds_recently_added"),
            "acquisition",
        ),
        (
            "by-author",
            "By Author",
            f"{author_count} author(s)",
            _shelf_url(request, "opds_authors"),
            "navigation",
        ),
        (
            "unmatched",
            "Unmatched",
            f"{unmatched} file(s) not linked to a tracked book",
            _shelf_url(request, "opds_unmatched"),
            "acquisition",
        ),
        (
            "all",
            "All Books",
            f"{total} total book(s)",
            _shelf_url(request, "opds_all"),
            "acquisition",
        ),
    ]

    body = _build_navigation_feed(
        request,
        user,
        title=f"{user.username}'s Yamtrack library",
        self_url=_shelf_url(request, "opds_root"),
        sections=sections,
    )
    return HttpResponse(body, content_type=NAV_TYPE)


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_up_next(request):
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    return _acquisition_response(
        request,
        user,
        list(_files_in_progress(user)),
        title="Up Next",
        self_url=_shelf_url(request, "opds_up_next"),
    )


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_want_to_read(request):
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    return _acquisition_response(
        request,
        user,
        list(_files_planning(user)),
        title="Want to Read",
        self_url=_shelf_url(request, "opds_want_to_read"),
    )


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_recently_added(request):
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    return _acquisition_response(
        request,
        user,
        list(_files_recently_added(user)),
        title="Recently Added",
        self_url=_shelf_url(request, "opds_recently_added"),
    )


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_unmatched(request):
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    return _acquisition_response(
        request,
        user,
        list(_files_unmatched(user)),
        title="Unmatched",
        self_url=_shelf_url(request, "opds_unmatched"),
    )


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_all(request):
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    return _acquisition_response(
        request,
        user,
        list(_files_all(user)),
        title="All Books",
        self_url=_shelf_url(request, "opds_all"),
    )


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_authors(request):
    """Navigation feed: one entry per distinct author in the user's library."""
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    authors = list(_distinct_authors(user))
    # Slug-id needs to be ASCII-safe and stable per author; the URL-encoded
    # name is good enough since it's deterministic and matches what shows up
    # in the href.
    sections = [
        (
            f"author:{quote(name)}",
            name,
            "",
            _author_url(request, name),
            "acquisition",
        )
        for name in authors
    ]
    body = _build_navigation_feed(
        request,
        user,
        title="By Author",
        self_url=_shelf_url(request, "opds_authors"),
        sections=sections,
    )
    return HttpResponse(body, content_type=NAV_TYPE)


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_author(request):
    """Acquisition feed for files by a single author (``?a=<name>``)."""
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    author = request.GET.get("a", "")
    if not author:
        return HttpResponse(status=400, content_type="application/xml")
    files = list(_files_by_author(user, author))
    self_url = _author_url(request, author)
    return _acquisition_response(
        request,
        user,
        files,
        title=author,
        self_url=self_url,
    )


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_download(request, pk):
    """Stream a LibraryFile back to the OPDS client with the canonical name."""
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    library_file = get_object_or_404(LibraryFile, pk=pk, user=user)

    response = FileResponse(
        stream_iter(library_file.file),
        content_type=library_file.mime_type or "application/epub+zip",
    )
    # RFC 6266 filename* uses UTF-8 with percent-encoding so titles with
    # non-ASCII chars (likely on every non-English library) survive the
    # round-trip into KOReader. The plain ``filename=`` form is kept as
    # a fallback for older clients.
    encoded = quote(library_file.canonical_filename, safe="")
    response["Content-Disposition"] = (
        f'attachment; filename="{library_file.canonical_filename}"; '
        f"filename*=UTF-8''{encoded}"
    )
    response["Content-Length"] = str(library_file.size_bytes or library_file.file.size)
    return response
