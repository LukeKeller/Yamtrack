from django.urls import path
from django.views.generic.base import RedirectView

from integrations import koreader, views

urlpatterns = [
    path("import/trakt-oauth", views.trakt_oauth, name="trakt_oauth"),
    path(
        "import/trakt/private",
        views.import_trakt_private,
        name="import_trakt_private",
    ),
    path("import/trakt/public", views.import_trakt_public, name="import_trakt_public"),
    path("import/simkl-oauth", views.simkl_oauth, name="simkl_oauth"),
    path(
        "import/simkl_private",
        views.import_simkl_private,
        name="import_simkl_private",
    ),
    path("import/mal", views.import_mal, name="import_mal"),
    path("import/anilist/oauth", views.anilist_oauth, name="import_anilist_oauth"),
    path(
        "import/anilist/private",
        views.import_anilist_private,
        name="import_anilist_private",
    ),
    path(
        "import/anilist/public",
        views.import_anilist_public,
        name="import_anilist_public",
    ),
    path("import/kitsu", views.import_kitsu, name="import_kitsu"),
    path("import/yamtrack", views.import_yamtrack, name="import_yamtrack"),
    path("import/hltb", views.import_hltb, name="import_hltb"),
    path("import/steam", views.import_steam, name="import_steam"),
    path("import/imdb", views.import_imdb, name="import_imdb"),
    path("import/goodreads", views.import_goodreads, name="import_goodreads"),
    path("import/hardcover", views.import_hardcover, name="import_hardcover"),
    path("hardcover/connect", views.hardcover_connect, name="hardcover_connect"),
    path(
        "hardcover/disconnect",
        views.hardcover_disconnect,
        name="hardcover_disconnect",
    ),
    path("import/discogs", views.import_discogs, name="import_discogs"),
    path("import/scrobbles", views.import_scrobbles, name="import_scrobbles"),
    path("export/csv", views.export_csv, name="export_csv"),
    path(
        "webhook/jellyfin/<str:token>",
        views.jellyfin_webhook,
        name="jellyfin_webhook",
    ),
    path(
        "webhook/plex/<str:token>",
        views.plex_webhook,
        name="plex_webhook",
    ),
    path(
        "webhook/emby/<str:token>",
        views.emby_webhook,
        name="emby_webhook",
    ),
    path(
        "api/scrobble/listenbrainz/1/validate-token",
        views.listenbrainz_validate_token,
        name="listenbrainz_validate_token",
    ),
    path(
        "api/scrobble/listenbrainz/1/user/<str:user_name>/listens",
        views.listenbrainz_get_listens,
        name="listenbrainz_get_listens",
    ),
    path(
        "api/scrobble/listenbrainz/1/submit-listens",
        views.listenbrainz_submit_listens,
        name="listenbrainz_submit_listens",
    ),
    path("api/quick-log/<str:token>", views.quick_log, name="quick_log"),
    path(
        "api/koreader/users/create",
        koreader.users_create,
        name="koreader_users_create",
    ),
    path(
        "api/koreader/users/auth",
        koreader.users_auth,
        name="koreader_users_auth",
    ),
    path(
        "api/koreader/syncs/progress",
        koreader.progress_put,
        name="koreader_progress_put",
    ),
    path(
        "api/koreader/syncs/progress/<str:document>",
        koreader.progress_get,
        name="koreader_progress_get",
    ),
    # POST endpoints — kept under /koreader/ since they're invoked by
    # forms that read the action via {% url 'koreader_link' %} and so on,
    # which is path-agnostic. No need to migrate them under /reading/.
    path("koreader/link", views.koreader_link, name="koreader_link"),
    path("koreader/unlink", views.koreader_unlink, name="koreader_unlink"),
    # Legacy redirects: GET sub-pages moved to /reading/koreader/...
    # The new path() entries live in reading/urls.py so URL names resolve
    # to the new location for the rest of the app; these redirects only
    # handle direct hits on the old paths (existing bookmarks, etc.).
    # /koreader/history/<book_pk> is intentionally not redirected — the
    # per-book history is now inlined on the book detail page, and the
    # source/media_type/media_id triple needed to build that URL isn't
    # encoded in the legacy path.
    path(
        "koreader/devices",
        RedirectView.as_view(pattern_name="koreader_devices", permanent=False),
    ),
    path(
        "koreader/unmatched",
        RedirectView.as_view(pattern_name="koreader_unmatched", permanent=False),
    ),
    path(
        "koreader/cadence",
        RedirectView.as_view(pattern_name="koreader_cadence", permanent=False),
    ),
    path(
        "koreader/sessions",
        RedirectView.as_view(pattern_name="koreader_sessions", permanent=False),
    ),
]
