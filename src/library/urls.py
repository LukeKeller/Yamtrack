"""Library + OPDS URL routes.

``/library/`` is the in-app browser; ``/library/opds/`` is the public OPDS
catalog KOReader hits. Both live under the user-Login middleware *except*
the OPDS endpoints, which use HTTP Basic against ``User.token`` so the
KOReader OPDS form can authenticate without going through allauth.

The OPDS catalog is a navigation feed at the root with six shelves
(Up Next / Want to Read / Recently Added / By Author / Unmatched /
All Books). Each shelf is its own acquisition feed; "By Author" is itself
a navigation feed whose entries are per-author acquisition feeds keyed by
``?a=<encoded author>``.
"""

from django.urls import path

from library import opds, views

urlpatterns = [
    path("", views.library_index, name="library_index"),
    path("upload", views.library_upload, name="library_upload"),
    path("file/<int:pk>/link", views.library_link, name="library_link"),
    path("file/<int:pk>/delete", views.library_delete, name="library_delete"),
    path("file/<int:pk>/rename", views.library_rename, name="library_rename"),
    path("opds/", opds.opds_root, name="opds_root"),
    path("opds/up-next", opds.opds_up_next, name="opds_up_next"),
    path("opds/want-to-read", opds.opds_want_to_read, name="opds_want_to_read"),
    path("opds/recently-added", opds.opds_recently_added, name="opds_recently_added"),
    path("opds/authors", opds.opds_authors, name="opds_authors"),
    path("opds/author", opds.opds_author, name="opds_author"),
    path("opds/unmatched", opds.opds_unmatched, name="opds_unmatched"),
    path("opds/all", opds.opds_all, name="opds_all"),
    path("opds/file/<int:pk>", opds.opds_download, name="opds_download"),
]
