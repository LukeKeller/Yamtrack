"""Fork-version release notes surfaced through the What's New modal.

This file is the source of truth for the fork's version identifier and for the
per-version changelog rendered on first load after each YunoHost upgrade. The
modal compares ``request.user.last_seen_version`` against ``CURRENT_FORK_VERSION``
and shows every entry newer than what the user has dismissed.

Bump ``CURRENT_FORK_VERSION`` whenever a new ``Bump fork package`` marker lands
on ``dev`` and prepend a matching entry to ``RELEASE_NOTES`` (newest first).
"""

CURRENT_FORK_VERSION = "0.25.2~ynh67"


RELEASE_NOTES = [
    {
        "version": "0.25.2~ynh67",
        "date": "2026-05-23",
        "title": "Big feature batch",
        "highlights": [
            "What's New modal: see this list on every upgrade so changes never sneak in silently.",
            "Polish: cross-document view transitions and a UI density toggle in preferences (compact / comfortable / cozy).",
            "Keyboard: J/K to move between rows, / to focus search, ? for a shortcut overlay.",
            "Notes: ||spoiler|| markdown that blurs until clicked, plus a one-tap Copy as Markdown on every media page.",
            "Open in: deep links to Plex, Infuse, VLC, Steam, Storygraph, Goodreads — pick your preferred player in preferences.",
            "Re-engagement: Next-Up widget for in-progress shows and an On This Day panel on the home page.",
            "Nudges: stale-planning badges for items sitting in Planning for over six months.",
            "Discovery: mood / vibe filter chips (Short, Long, Funny, Dark, Cozy, Highly-rated, Unrewatched).",
            "Discovery: 'Comparable to' panel on media detail pages, computed from your own ratings.",
            "Cross-media: year-long heat calendar on Statistics, color-coded by minutes consumed across every media type.",
            "Cross-media: genre / mood fatigue detector that suggests a palate cleanser from your Planning list.",
            "PWA: Web Share Target — share a TMDB/IMDB/AniList link from any browser straight into Yamtrack.",
            "PWA: app badge for unread What's New count on supported platforms.",
            "Multi-user: per-friend compatibility score and per-item privacy (public / friends / private).",
            "Calendar: per-list iCal feeds at /calendar/<list_id>.ics so partners can subscribe to shared lists.",
            "Self-host: Apprise notification templating and a /api/quick-log endpoint for Shortcuts / Tasker / Siri.",
            "Stats: first-of-month recap notification and a re-pivotable Year-in-Review URL.",
            "Command palette: verb actions — search a title and pick Set status / Rate / Open from the result.",
        ],
        "fixes": [],
    },
]


def entries_since(last_seen_version: str | None):
    """Return release-note entries newer than ``last_seen_version``.

    If ``last_seen_version`` is empty/None, returns every entry. If the value
    isn't in the list (older or unknown), returns every entry too so users on
    a stale value still see what changed.
    """
    if not last_seen_version:
        return list(RELEASE_NOTES)

    for index, entry in enumerate(RELEASE_NOTES):
        if entry["version"] == last_seen_version:
            return RELEASE_NOTES[:index]
    return list(RELEASE_NOTES)
