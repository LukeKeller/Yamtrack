# ruff: noqa: E501 — release-note strings are content, not code; don't wrap them
"""Fork-version release notes surfaced through the What's New modal.

This file is the source of truth for the fork's version identifier and for the
per-version changelog rendered on first load after each YunoHost upgrade. The
modal compares ``request.user.last_seen_version`` against ``CURRENT_FORK_VERSION``
and shows every entry newer than what the user has dismissed.

Bump ``CURRENT_FORK_VERSION`` whenever a new ``Bump fork package`` marker lands
on ``dev`` and prepend a matching entry to ``RELEASE_NOTES`` (newest first).
"""

CURRENT_FORK_VERSION = "0.25.2~ynh77"


RELEASE_NOTES = [
    {
        "version": "0.25.2~ynh77",
        "date": "2026-05-23",
        "title": "Compact home calendar when nothing is scheduled",
        "highlights": [
            "Home page: when the current month has no scheduled releases, the calendar widget collapses from a ~600px empty grid to a compact one-line card with a 'Fetch releases' button and a link to the full calendar. The full /calendar page is unchanged.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh76",
        "date": "2026-05-23",
        "title": "Home page deep links",
        "highlights": [
            "Each per-media-type subsection on the home page (TV Seasons / Movies / Books / etc.) now has a 'View all →' link that drills into the corresponding filtered media list.",
            "The Today section's date is now a link to the full calendar page.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh75",
        "date": "2026-05-23",
        "title": "Today section, mobile-friendly calendar, search results polish",
        "highlights": [
            "Home page: new Today section above the calendar listing what's airing today (only shows when there's actually something).",
            "Mobile: calendar widget forces the list view below the `sm` breakpoint — the 7-column grid cells are too narrow on a phone, titles get truncated to a single letter. List view shows each day with full titles and times.",
            "Mobile: calendar header collapses the 'Fetch New Releases' label to an icon-only button to save horizontal space, and hides the desktop-only grid/list view toggle.",
            "Search results page: header now echoes the query you searched (e.g. 'Results for \"severance\"') with the media type as a tracker chip and result count below; source filters use rounded pill chips on theme tokens; pagination active page uses the accent colour.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh74",
        "date": "2026-05-23",
        "title": "Readable calendar event chips",
        "highlights": [
            "Calendar event chips inside each day cell now use a two-line layout: title on top, time on a faint second line — plus a left-edge color bar tinted by media-type so movies/shows/anime are easy to scan at a glance.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh73",
        "date": "2026-05-23",
        "title": "More home polish",
        "highlights": [
            "Hero status chips are now clickable — jump straight to the In Progress / Planning section further down the page.",
            "Recent activity icons get a much stronger badge (saturated background + ring-cut into the timeline line) so events read at a glance.",
            "Per-media-type subsection headers ('TV Seasons', 'Movies', etc.) get a thin accent bar matching the parent status and a faint count.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh72",
        "date": "2026-05-23",
        "title": "Per-user timezone, Recent activity timeline, Steam ID validation",
        "highlights": [
            "Per-user timezone setting in Preferences. Pick your IANA zone (e.g. America/New_York) and calendar event times, 'today' boundaries, and Recent activity timestamps all render in your local time instead of UTC.",
            "Recent activity gets a timeline treatment: a subtle vertical line behind the icon column with each event ring-cut into it. Replaces the previous divider-line list.",
        ],
        "fixes": [
            "Steam import now validates the SteamID field up front and tells you when you've pasted your API key instead of your numeric ID, instead of throwing a confusing HTTP 400 mid-task.",
        ],
    },
    {
        "version": "0.25.2~ynh71",
        "date": "2026-05-23",
        "title": "More home polish + import-now + Sunday calendar",
        "highlights": [
            "Up Next: bigger poster (14x20 with a subtle ring), cleaner metadata stack, slim accent-coloured progress bar at the bottom of each card, and the +1 button repositioned to a floating shadow on hover.",
            "Section headers: every block on the home page (Up next, On this day, Still in planning, Recent activity, Your library) gets a small accent dot to the left of the title for consistent visual rhythm.",
            "Calendar widget now sits above Recent activity on the home page.",
            "Calendar weeks start on Sunday (US convention) instead of Monday.",
            "Scheduled imports get an Import now button next to the delete icon — kicks off the same Celery task immediately instead of waiting for the crontab.",
        ],
        "fixes": [
            "Greeting no longer renders 'Welcome back , luke' with a stray space before the comma (djlint reformat artifact).",
        ],
    },
    {
        "version": "0.25.2~ynh70",
        "date": "2026-05-23",
        "title": "Home page polish",
        "highlights": [
            "Home hero: tighter date/greeting cluster, status chips below the title showing counts at a glance.",
            "Moved the sort selector down to its actual section ('Your library') instead of floating up top.",
        ],
        "fixes": [
            "Tailwind catch-up: rebuilt main.css so utilities like -mt-1, w-1, max-w-lg, items-baseline (introduced in ynh67/68 templates) now actually apply.",
        ],
    },
    {
        "version": "0.25.2~ynh69",
        "date": "2026-05-23",
        "title": "Hotfix: person pages",
        "highlights": [],
        "fixes": [
            "Person detail pages were 500ing — person_stats was treating the Media model as a dict. Switched to attribute access.",
        ],
    },
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
