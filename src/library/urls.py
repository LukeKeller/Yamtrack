"""Library URL routes — OPDS feed plus legacy redirects.

The browser-facing pages (uploads, link, rename, delete) moved to
``/reading/library/...`` in ynh-reading-hub. They keep their URL *names*
(``library_index``, ``library_upload``, ...) so ``{% url %}`` references
across the codebase keep resolving; only the resolved path changes. The
actual ``path()`` registrations are in ``reading/urls.py``.

The OPDS endpoints stay mounted at ``/library/opds/...`` exactly as
before — KOReader devices already subscribe to that URL and re-pinning
every device would be hostile. They authenticate via HTTP Basic against
``User.token``, not via session middleware.

The OPDS catalog is a navigation feed at the root with six shelves
(Up Next / Want to Read / Recently Added / By Author / Unmatched /
All Books). Each shelf is its own acquisition feed; "By Author" is
itself a navigation feed whose entries are per-author acquisition
feeds keyed by ``?a=<encoded author>``.

Anything that hits the old ``/library/...`` browser URLs gets a 302 to
the new ``/reading/library/...`` location so existing bookmarks survive.
"""

from django.urls import path
from django.views.generic.base import RedirectView

from library import opds

urlpatterns = [
    # OPDS catalog — load-bearing; KOReader subscription URL.
    path("opds/", opds.opds_root, name="opds_root"),
    path("opds/up-next", opds.opds_up_next, name="opds_up_next"),
    path("opds/want-to-read", opds.opds_want_to_read, name="opds_want_to_read"),
    path("opds/recently-added", opds.opds_recently_added, name="opds_recently_added"),
    path("opds/authors", opds.opds_authors, name="opds_authors"),
    path("opds/author", opds.opds_author, name="opds_author"),
    path("opds/unmatched", opds.opds_unmatched, name="opds_unmatched"),
    path("opds/all", opds.opds_all, name="opds_all"),
    path("opds/file/<int:pk>", opds.opds_download, name="opds_download"),
    # Legacy redirects: /library/* browser URLs moved under /reading/library/.
    path(
        "",
        RedirectView.as_view(pattern_name="library_index", permanent=False),
    ),
    path(
        "upload",
        RedirectView.as_view(pattern_name="library_upload", permanent=False),
    ),
    path(
        "file/<int:pk>/link",
        RedirectView.as_view(pattern_name="library_link", permanent=False),
    ),
    path(
        "file/<int:pk>/delete",
        RedirectView.as_view(pattern_name="library_delete", permanent=False),
    ),
    path(
        "file/<int:pk>/rename",
        RedirectView.as_view(pattern_name="library_rename", permanent=False),
    ),
]
