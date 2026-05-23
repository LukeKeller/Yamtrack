"""Fork-version release notes surfaced through the What's New modal.

This file is the source of truth for the fork's version identifier and for the
per-version changelog rendered on first load after each YunoHost upgrade. The
modal compares ``request.user.last_seen_version`` against ``CURRENT_FORK_VERSION``
and shows every entry newer than what the user has dismissed.

Bump ``CURRENT_FORK_VERSION`` whenever a new ``Bump fork package`` marker lands
on ``dev`` and prepend a matching entry to ``RELEASE_NOTES`` (newest first).
"""

CURRENT_FORK_VERSION = "0.25.2~ynh68"


RELEASE_NOTES = [
    {
        "version": "0.25.2~ynh68",
        "date": "2026-05-23",
        "title": "Pre-deploy hotfix",
        "highlights": [],
        "fixes": [
            "What's New modal: the max-height constraint relies on an arbitrary Tailwind class that wasn't in main.css — swapped to one that is, so the modal scrolls inside the viewport instead of spilling past it.",
        ],
    },
    {
        "version": "0.25.2~ynh67",
        "date": "2026-05-23",
        "title": "Big feature batch",
        "highlights": [
            "What's New modal — this list, shown automatically on first load after every upgrade.",
            "Polish: HTMX swaps opted into the View Transitions API so status changes morph instead of jumping.",
            "Polish: ARIA live region and focus restoration after HTMX swaps so screen readers track changes too.",
            "Keyboard: `?` opens a shortcut cheat-sheet, J/K moves focus between media cards, `/` focuses search.",
            "Notes: `||spoiler||` markdown blurs text until clicked, plus a one-tap Copy as Markdown button on every media page.",
            "Re-engagement: On This Day panel on the home page surfaces what you started or completed today in past years.",
            "Re-engagement: 'Still in planning' nudge for items sitting in Planning longer than six months.",
            "Re-engagement: palate-cleanser card when one media type accounts for >70% of recent activity.",
            "Discovery: mood / vibe filter chips on every media list — Highly rated, Recently completed, Stuck, Unrewatched 3y+.",
            "Discovery: 'Comparable in your library' panel on media detail pages, computed from your own ratings.",
            "Insights: per-person stats panel on TMDB person pages (tracked count, average score, 8+ rated).",
            "PWA: Web Share Target — share a TMDB/IMDB/AniList link from any browser straight into Yamtrack's search.",
            "PWA: app badge for unread What's New on supported platforms (Chromium desktop, iOS PWA).",
            "Calendar: per-list iCal feeds at /calendar/download/<token>/list/<id> so collaborators can subscribe to shared lists.",
            "Self-host: /integrations/api/quick-log/<token> endpoint for advancing items from Shortcuts / Tasker / Siri / bots.",
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
