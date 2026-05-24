# ruff: noqa: E501 — release-note strings are content, not code; don't wrap them
"""Fork-version release notes surfaced through the What's New modal.

This file is the source of truth for the fork's version identifier and for the
per-version changelog rendered on first load after each YunoHost upgrade. The
modal compares ``request.user.last_seen_version`` against ``CURRENT_FORK_VERSION``
and shows every entry newer than what the user has dismissed.

Bump ``CURRENT_FORK_VERSION`` whenever a new ``Bump fork package`` marker lands
on ``dev`` and prepend a matching entry to ``RELEASE_NOTES`` (newest first).
"""

CURRENT_FORK_VERSION = "0.25.2~ynh88"


RELEASE_NOTES = [
    {
        "version": "0.25.2~ynh88",
        "date": "2026-05-24",
        "title": "Year in review page",
        "highlights": [
            "New 'Year in review' page at /wrapped/ — a Spotify-Wrapped-style recap of what you completed in a given year. Year chips at the top jump between the current year and the two prior years; 'All time' bounces to the regular Statistics page.",
            "Includes hero stat cards (completions, items tracked, current streak, longest streak), per-media-type counts, a 'biggest month' callout, a month-by-month bar chart, your top-rated titles for the year, and your most-active day of the week.",
            "Link added at the top right of the Statistics page so you can jump into it from the existing flow.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh87",
        "date": "2026-05-24",
        "title": "Your score now shows out of 10",
        "highlights": [
            "The 'Your score' box on media detail pages now displays the score as a number out of 10 (e.g. '8/10') instead of a 5-star widget with a halved value. This matches the way IMDb, Hardcover, and TMDB scores are already shown right next to it on the same page, and matches the way scores already appear on cards, list rows, and the statistics page.",
            "Picker behaviour is unchanged — click 'Your score' and you still get the 1-10 dot row.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh86",
        "date": "2026-05-24",
        "title": "Fork version visible in Settings",
        "highlights": [
            "The current fork build (e.g. 0.25.2~ynh86) now shows at the bottom of the Settings sidebar so you can confirm at a glance which build is running after a YunoHost upgrade.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh85",
        "date": "2026-05-24",
        "title": "Themes, font picker, live theme preview",
        "highlights": [
            "Six new themes — Rosé Pine Moon, Monokai Pro, Solarized Dark, Catppuccin Latte (light), Solarized Light, Newsprint (sepia), plus a bold Synthwave option. The previous eight were all mid-blue darks; this brings real variety.",
            "Newsprint pairs warm aged-paper surfaces with a deep ink-red accent, and is designed to pair with the new Typewriter font for a full vintage broadsheet look.",
            "New font picker in Settings → Preferences: System, Serif, Monospace, Rounded, Humanist, Typewriter. All options use OS-native font stacks — zero network requests, no privacy concerns.",
            "Theme picker now updates instantly when you click a swatch and previews the palette across the whole page live (was server-rendering the selection, so clicking did nothing until you saved).",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh84",
        "date": "2026-05-24",
        "title": "Fix: mobile sticky CTA opened a blank track drawer",
        "highlights": [],
        "fixes": [
            "Tapping the sticky bottom CTA on a media detail page on mobile (e.g. 'In Progress' on a book, 'Add to library' on anything not yet tracked) opened the track drawer but the drawer body was empty. The CTA only fired the open-drawer event and never issued the HTMX request that loads the form — a regression introduced when ynh79 hid the in-poster CTA on mobile and made this button the sole entry point. Restored by pairing the event with the matching hx-get, mirroring the desktop status-sheet branches.",
        ],
    },
    {
        "version": "0.25.2~ynh83",
        "date": "2026-05-24",
        "title": "Fix: book track drawer rendering a Django comment as text",
        "highlights": [],
        "fixes": [
            "The Pages ↔ Percent toggle on the book tracking drawer was rendering its multi-line {# … #} explanation as visible text whenever total page count was known. Replaced with a {% comment %} block so the comment is stripped at render time.",
            "Fixed the pre-commit hook that's supposed to catch this exact mistake: it was silently passing on macOS because it shelled out to `grep -P`, which BSD grep doesn't support. Rewritten in Python so it runs on both Linux and macOS, and added a portable file-list loop for the no-args branch.",
        ],
    },
    {
        "version": "0.25.2~ynh82",
        "date": "2026-05-24",
        "title": "Hardcover sync: push book progress on save",
        "highlights": [
            "Connect a Hardcover.app account from Settings → Integrations by pasting a personal access token (get yours at hardcover.app/account/api). The token is encrypted at rest with the same Fernet key as other integrations.",
            "When you save a change to a tracked book in Yamtrack — progress, status, score, start/end dates — it now pushes to your Hardcover library within ~10 seconds. Rapid edits collapse into one push.",
            "New Pages ↔ % toggle in the book tracking drawer: type pages or percent, the other unit updates live (and the form always submits pages, so nothing changes on the API side).",
            "Book pages are resolved into Hardcover books via ISBN-13 first, with title+author fallback. Results are cached so repeat pushes for the same book skip the lookup.",
            "Two-layer echo suppression keeps the existing Hardcover importer and the new outbound push from looping: a thread-local flag for in-process bulk imports, plus a 10-second timestamp window per book.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh81",
        "date": "2026-05-23",
        "title": "Quick-rate from cards: kebab popover + 1-9 / 0 hotkeys",
        "highlights": [
            "Click the kebab on any tracked media card to get a one-tap 1-10 rating row before the existing actions. The current score is highlighted, and the on-poster score badge updates immediately without a page reload.",
            "New keyboard hotkeys: focus a card with J/K, then press 1-9 to rate it that value, or 0 to set it to 10. Untracked cards and episode cards are skipped. Modifier-key combos (Ctrl/Cmd+digit) are left alone so browser shortcuts still work.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh80",
        "date": "2026-05-23",
        "title": "Auto-mark prior episodes (binge-mode opt-in)",
        "highlights": [
            "New Preferences toggle: when marking an episode as watched, any earlier un-tracked episodes in the same season are marked too. Off by default. Useful if you binge first and log later — mark S2E8 and S2E1-7 get filled in. Unaired episodes are skipped, the marked date is shared, and existing tracked episodes aren't disturbed.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh79",
        "date": "2026-05-23",
        "title": "Tighter mobile media-detail hero",
        "highlights": [
            "Media detail pages on mobile: poster is capped at 180px (down from 250px), the hero's top padding is tightened, and the title shrinks one step. Together this lifts the title roughly 150px up so it's above the fold on a phone instead of below the poster + button stack.",
            "The in-poster 'Add to library' / status button is hidden on mobile — it was duplicated by the bottom sticky CTA that already follows you down the page. Desktop is unchanged (the sidebar poster column still owns the CTA there).",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh78",
        "date": "2026-05-23",
        "title": "Preferences page no longer crashes when TMDB is unreachable",
        "highlights": [],
        "fixes": [
            "Settings → Preferences: the watch-provider region dropdown fetches its list from TMDB; if the TMDB key was invalid or the API was unreachable, the whole preferences page would 500 and you couldn't change your theme, timezone, or any other setting. It now degrades gracefully — the dropdown shows 'Disabled' and the rest of the page renders normally.",
        ],
    },
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
