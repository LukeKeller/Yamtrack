"""Reading hub URL routes.

``/reading/`` is the new landing surface for everything book-shaped. The
library browser (uploads, link, delete, rename) and KOReader workspace
sub-pages (cadence, sessions, devices, unmatched) move under this prefix
so users don't have to bounce through ``Settings → Integrations``.

Two things deliberately stay where they were:

* ``/library/opds/`` — the OPDS catalog. KOReader devices already
  subscribe to this URL and re-pinning every device would be hostile.
  Defined in ``library/urls.py``.
* ``/api/koreader/...`` — the kosync wire protocol endpoints. Same
  argument. Defined in ``integrations/urls.py``.

The URL *names* (``library_index``, ``koreader_cadence``, etc.) are
preserved across the move so templates and ``{% url %}`` references in
the rest of the codebase don't need a search-and-replace; only the
resolved paths change.
"""

from django.urls import path

from integrations import views as integrations_views
from library import views as library_views
from reading import views as reading_views

urlpatterns = [
    path("", reading_views.reading_index, name="reading_index"),
    path("unmatched", reading_views.reading_unmatched, name="reading_unmatched"),
    # Library browser — was /library/{index,upload,file/<pk>/...}
    path("library/", library_views.library_index, name="library_index"),
    path("library/upload", library_views.library_upload, name="library_upload"),
    path(
        "library/file/<int:pk>/link",
        library_views.library_link,
        name="library_link",
    ),
    path(
        "library/file/<int:pk>/delete",
        library_views.library_delete,
        name="library_delete",
    ),
    path(
        "library/file/<int:pk>/rename",
        library_views.library_rename,
        name="library_rename",
    ),
    # KOReader workspace — was /koreader/{cadence,sessions,devices,unmatched}.
    # Per-book history used to live at koreader/history/<book_pk> but is now
    # inlined on the book detail page.
    path(
        "koreader/cadence",
        integrations_views.koreader_cadence,
        name="koreader_cadence",
    ),
    path(
        "koreader/sessions",
        integrations_views.koreader_sessions,
        name="koreader_sessions",
    ),
    path(
        "koreader/devices",
        integrations_views.koreader_devices,
        name="koreader_devices",
    ),
    path(
        "koreader/unmatched",
        integrations_views.koreader_unmatched,
        name="koreader_unmatched",
    ),
]
