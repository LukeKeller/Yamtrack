from django.urls import path, register_converter

from app import converters, views

register_converter(converters.MediaTypeChecker, "media_type")
register_converter(converters.SourceChecker, "source")


urlpatterns = [
    path("", views.home, name="home"),
    path("medialist/<media_type:media_type>", views.media_list, name="medialist"),
    path("search", views.media_search, name="search"),
    path("browse", views.browse, name="browse"),
    path(
        "details/<source:source>/<media_type:media_type>/<str:media_id>/<str:title>",
        views.media_details,
        name="media_details",
    ),
    path(
        "details/<source:source>/tv/<str:media_id>/<str:title>/season/<int:season_number>",
        views.season_details,
        name="season_details",
    ),
    path(
        "person/<int:person_id>/<str:name>",
        views.person_details,
        name="person_details",
    ),
    path(
        # ``path:`` lets artist names with slashes through (AC/DC, etc.).
        # No other route lives under ``/artist/<...>`` so the greedy match
        # is safe.
        "artist/<path:name>",
        views.artist_details,
        name="artist_details",
    ),
    path(
        "update-score/<media_type:media_type>/<int:instance_id>",
        views.update_media_score,
        name="update_media_score",
    ),
    path(
        "update-status/<media_type:media_type>/<int:instance_id>",
        views.update_media_status,
        name="update_media_status",
    ),
    path(
        "details/sync/<source:source>/<media_type:media_type>/<str:media_id>",
        views.sync_metadata,
        name="sync_metadata",
    ),
    path(
        "details/sync/<source:source>/<media_type:media_type>/<str:media_id>/<int:season_number>",
        views.sync_metadata,
        name="sync_metadata",
    ),
    path(
        "track_modal/<source:source>/<media_type:media_type>/<str:media_id>",
        views.track_modal,
        name="track_modal",
    ),
    path(
        "track_modal/<source:source>/<media_type:media_type>/<str:media_id>/<int:season_number>",
        views.track_modal,
        name="track_modal",
    ),
    path(
        "progress_edit/<media_type:media_type>/<int:instance_id>",
        views.progress_edit,
        name="progress_edit",
    ),
    path("media_save", views.media_save, name="media_save"),
    path("media_delete", views.media_delete, name="media_delete"),
    path("dismiss_item", views.dismiss_item, name="dismiss_item"),
    path(
        "user_messages/mark_shown",
        views.mark_user_messages_shown,
        name="mark_user_messages_shown",
    ),
    path("episode_save", views.episode_save, name="episode_save"),
    path(
        "history_modal/<source:source>/<media_type:media_type>/<str:media_id>",
        views.history_modal,
        name="history_modal",
    ),
    path(
        "history_modal/<source:source>/<media_type:media_type>/<str:media_id>/<int:season_number>",
        views.history_modal,
        name="history_modal",
    ),
    path(
        "history_modal/<source:source>/<media_type:media_type>/<str:media_id>/<int:season_number>/<int:episode_number>",
        views.history_modal,
        name="history_modal",
    ),
    path(
        "media/history/<str:media_type>/<int:history_id>/delete/",
        views.delete_history_record,
        name="delete_history_record",
    ),
    path("create", views.create_entry, name="create_entry"),
    path("search/parent_tv", views.search_parent_tv, name="search_parent_tv"),
    path(
        "search/parent_season",
        views.search_parent_season,
        name="search_parent_season",
    ),
    path("statistics", views.statistics, name="statistics"),
    path("wrapped/", views.wrapped, name="wrapped"),
    path("wrapped/<int:year>/", views.wrapped, name="wrapped_year"),
    path(
        "play/record/spin/<source:source>/<str:media_id>",
        views.log_record_spin,
        name="log_record_spin",
    ),
    path("music/history", views.music_history, name="music_history"),
    path("music/stats", views.music_stats, name="music_stats"),
    path("music/unmatched", views.music_unmatched, name="music_unmatched"),
    path(
        "music/unmatched/search",
        views.match_record_search,
        name="match_record_search",
    ),
    path(
        "music/unmatched/apply",
        views.match_unmatched_apply,
        name="match_unmatched_apply",
    ),
    path("serviceworker.js", views.service_worker, name="service_worker"),
    path("site.webmanifest", views.webmanifest, name="webmanifest"),
    path("cmdk/search", views.cmdk_search, name="cmdk_search"),
    path("share-intake/", views.share_intake, name="share_intake"),
]
