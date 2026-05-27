"""OPDS 1.2 catalog + acquisition feed for the library.

KOReader's "Add OPDS catalog" form sends HTTP Basic credentials; we map
the username to the Yamtrack username and the password to the user's
raw integration token (``User.token``), the same token used to mint the
kosync ``x-auth-key`` header (md5-ed) and the Jellyfin/Plex webhook
paths. Using the existing token means OPDS access tracks the rest of
the per-user API surface — regenerating the token revokes everything in
one shot.

Two endpoints:

* ``GET /library/opds/`` — single acquisition feed listing every
  LibraryFile the user owns, newest first. KOReader treats acquisition
  feeds as browseable lists; download links carry a typed
  ``application/epub+zip`` rel.
* ``GET /library/opds/file/<pk>`` — streams the epub with
  ``Content-Disposition: attachment; filename="<canonical>.epub"`` so
  KOReader saves the file under the basename we md5'd at upload time.
  That basename's md5 equals the kosync ``document`` hash KOReader will
  push on first open → auto-bind on next sync without ever passing
  through ``/koreader/unmatched``.

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
from library.helpers import stream_iter
from library.models import LibraryFile

logger = logging.getLogger(__name__)

OPDS_NAMESPACE = "http://www.w3.org/2005/Atom"
OPDS_OPDS_NAMESPACE = "http://opds-spec.org/2010/catalog"
DC_NAMESPACE = "http://purl.org/dc/terms/"

ET.register_namespace("", OPDS_NAMESPACE)
ET.register_namespace("opds", OPDS_OPDS_NAMESPACE)
ET.register_namespace("dcterms", DC_NAMESPACE)


def _basic_auth_user(request):
    """Decode HTTP Basic; return the Yamtrack user matching token=password.

    Returns ``None`` on any failure — bad header, bad encoding, no user,
    wrong token. The 401 response (with WWW-Authenticate) is the
    caller's responsibility so we don't accidentally swallow real
    errors as auth failures.
    """
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    username, _, token = decoded.partition(":")
    if not username or not token:
        return None
    # Case-insensitive username (matches the kosync convention; KOReader
    # lowercases the OPDS username field for some users too — easier to
    # be permissive than to debug "why does my casing matter only here").
    for candidate in users.models.User.objects.filter(username__iexact=username):
        if candidate.token == token:
            return candidate
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


def _opds_self_url(request):
    """Absolute URL to the catalog root for the OPDS self link."""
    return request.build_absolute_uri(reverse("opds_root"))


def _build_acquisition_feed(request, user, files):
    """Return the OPDS acquisition feed XML for ``files``."""
    feed = ET.Element(f"{{{OPDS_NAMESPACE}}}feed")

    def _sub(parent, tag, text=None, *, ns=OPDS_NAMESPACE, **attrs):
        """Append a child element. ``tag`` is local, namespace via kwarg."""
        el = ET.SubElement(parent, f"{{{ns}}}{tag}", attrs)
        if text is not None:
            el.text = text
        return el

    self_url = _opds_self_url(request)
    _sub(feed, "id", f"yamtrack:library:{user.pk}")
    _sub(feed, "title", f"{user.username}'s Yamtrack library")
    _sub(feed, "updated", timezone.now().isoformat())

    author = _sub(feed, "author")
    _sub(author, "name", "Yamtrack")

    _sub(
        feed,
        "link",
        rel="self",
        href=self_url,
        type="application/atom+xml;profile=opds-catalog;kind=acquisition",
    )
    _sub(
        feed,
        "link",
        rel="start",
        href=self_url,
        type="application/atom+xml;profile=opds-catalog;kind=acquisition",
    )

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


@login_not_required
@require_http_methods(["GET", "HEAD"])
def opds_root(request):
    """Single acquisition feed listing every LibraryFile the user owns."""
    user = _basic_auth_user(request)
    if user is None:
        return _require_basic_auth(request)
    files = list(
        LibraryFile.objects.filter(user=user).order_by("-created_at").select_related(),
    )
    body = _build_acquisition_feed(request, user, files)
    return HttpResponse(
        body,
        content_type="application/atom+xml;profile=opds-catalog;kind=acquisition",
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
