"""Library + OPDS URL routes.

``/library/`` is the in-app browser; ``/library/opds/`` is the public OPDS
catalog KOReader hits. Both live under the user-Login middleware *except*
the OPDS endpoints, which use HTTP Basic against ``User.token`` so the
KOReader OPDS form can authenticate without going through allauth.
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
    path("opds/file/<int:pk>", opds.opds_download, name="opds_download"),
]
