from django.urls import path

from integrations import views

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
]
