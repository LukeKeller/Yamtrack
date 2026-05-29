# ruff: noqa: E501 — release-note strings are content, not code; don't wrap them
"""Fork-version release notes surfaced through the What's New modal.

This file is the source of truth for the fork's version identifier and for the
per-version changelog rendered on first load after each YunoHost upgrade. The
modal compares ``request.user.last_seen_version`` against ``CURRENT_FORK_VERSION``
and shows every entry newer than what the user has dismissed.

Bump ``CURRENT_FORK_VERSION`` whenever a new ``Bump fork package`` marker lands
on ``dev`` and prepend a matching entry to ``RELEASE_NOTES`` (newest first).
"""

CURRENT_FORK_VERSION = "0.25.2~ynh149"


RELEASE_NOTES = [
    {
        "version": "0.25.2~ynh149",
        "date": "2026-05-29",
        "title": "Games list: a playtime stats panel",
        "highlights": [
            'The games list (<span class="font-mono">/medialist/game</span>) gained a collapsible <strong>Playtime Stats</strong> panel, mirroring the records collection stats. Because a game\'s progress is tracked as minutes played, Yamtrack can total it: the panel shows your <strong>total playtime</strong> in hours, how many games you\'ve <strong>completed</strong>, the <strong>average</strong> playtime across games that have any time logged, and a <strong>Most played</strong> list ranking your top titles with a simple bar each. It only appears once you track at least one game, and games with no logged time are left out of the ranking. Playtime comes from whatever you\'ve logged manually or imported (e.g. HowLongToBeat / Steam).',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh148",
        "date": "2026-05-29",
        "title": "Home: unwatched-episode count badge on the Up Next rail",
        "highlights": [
            'Cards in the home <strong>Up Next</strong> rail now carry a small count badge on the cover when there are released episodes (or chapters) you haven\'t watched yet — the difference between what\'s aired and your progress. For a show you\'d already caught up on it stays hidden until a new episode airs, so the badge reads as a "new episode is out" nudge rather than a permanent "you\'re mid-binge" marker; for a back-catalogue binge it tells you how many are queued up. Movies are excluded (they\'d always show "1"), and anything without release data (e.g. an anime with no air-date schedule) simply shows no badge.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh147",
        "date": "2026-05-29",
        "title": "Year in review now counts pages read and reading time",
        "highlights": [
            'The <span class="font-mono">/wrapped/</span> year-in-review recap gained a <strong>Reading</strong> section. <strong>Pages read</strong> sums the page count of every book you finished that year (a book\'s progress <em>is</em> its page count, so no new tracking was needed), and <strong>Reading time</strong> totals the hours from your KOReader sync sessions whose start falls in the year, with the session count alongside. Each card only appears when it has something to show, so the section stays hidden for non-readers and shows just the half that applies if you have one without the other (pages without KOReader, or KOReader time without finishing a book that year). Video and game runtime are still left out — those need duration metadata Yamtrack doesn\'t store — but reading was always derivable and is no longer skipped.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh146",
        "date": "2026-05-29",
        "title": "Reading history: single-sync reading sessions no longer vanish",
        "highlights": [],
        "fixes": [
            'A reading session that KOReader pushed as a single progress update — offline reading flushed when you closed the book, a long autosync interval, or "sync on close" mode — was dropped from the inline reading history on the book details page, even though that same push had correctly advanced the book\'s progress and synced it to Hardcover. The session-grouping logic treated any lone, short sync event as a KOReader book-open ping and filtered it out. It now keeps a lone event when it advanced past the last synced position for that book (the signature of a real single-sync read) while still dropping pings that re-report the same position, and backfills the kept session\'s start to the prior position so the Book Journey chart shows the real progress delta instead of a flat bar. Note: a single-sync session still reads ~0&nbsp;min of <em>duration</em> — reading time is derived from the spread of sync timestamps, so keeping WiFi on while reading (which lets KOReader sync several times mid-session) is what makes the time totals accurate.',
        ],
    },
    {
        "version": "0.25.2~ynh145",
        "date": "2026-05-28",
        "title": "Browse: genre filter on TMDB rows + one-word nav label",
        "highlights": [
            'The TMDB browse page now carries a <strong>Genres</strong> chip row below the existing category strip — toggling a chip narrows whatever category is active (Popular, Top Rated, Streaming Now, Hidden Gems, Classics, For You, etc.) to titles tagged with that genre. Multi-select stacks (AND across selected genres), and a <span class="font-mono">Clear</span> link to the right of the row drops all selections. The filter is server-side: every category now routes through TMDB\'s <span class="font-mono">/discover/movie</span> or <span class="font-mono">/discover/tv</span> with <span class="font-mono">with_genres=…</span> when chips are active, with the original sort/window for each category mapped to its discover-equivalent so the semantics stay intact (e.g., Top Rated keeps <span class="font-mono">vote_average.desc</span> + a vote-count floor; Streaming Now keeps its 180-day window). For You is filtered after match-score sorting so the personalized order is preserved. Switching media type (Movies ↔ TV Shows) drops the chips because TMDB\'s movie/TV genre IDs don\'t share a vocabulary; switching source (TMDB ↔ Trakt) drops them because Trakt uses slugs, not IDs. The chip row hides entirely on Trakt.',
            'The mobile bottom bar said <span class="font-mono">Discover</span> while the side rail and page title said <span class="font-mono">Browse</span>. Standardized on <span class="font-mono">Browse</span> across both since that\'s also the URL slug.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh144",
        "date": "2026-05-28",
        "title": "Book Journey chart now actually draws (fixes double-encoded JSON)",
        "highlights": [
            'The inlined Reading history section landed in ~ynh143 but the Book Journey bar chart never drew — only the empty 420px canvas backdrop appeared. The view was passing <span class="font-mono">json.dumps(journey_data)</span> (a JSON string) into context and the template then ran it through <span class="font-mono">{% ...|json_script %}</span>, which JSON-encodes the value a second time. The script tag ended up carrying a quoted string literal, so <span class="font-mono">JSON.parse</span> in the chart JS returned a string instead of an array, the script logged "payload is not an array", and bailed silently. The view now hands a plain Python list to the template and lets <span class="font-mono">json_script</span> do the single encode. Chart redraws on the next page load.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh143",
        "date": "2026-05-28",
        "title": "Reading history is no longer a sub-page — chart and sessions inline on the book details page",
        "highlights": [
            'KOReader reading history used to live on its own page (<span class="font-mono">/reading/koreader/history/&lt;book&gt;</span>) — one extra click away from the book you were already looking at. The full history (stats grid, journey chart, sessions table) now renders inline on the book details page itself, right above the right-rail "Your History" column. The compact "KOReader" summary chip in the rail still shows the at-a-glance numbers; its "Full history" link is now a same-page anchor instead of bouncing you to a sub-page.',
            "Identical content to before, just stitched into the page you already opened: sync-event count, distinct devices, latest kosync percentage, total reading time, the journey bar chart, and the inferred-sessions table. Books with no KOReader events render nothing — same as the chip behaviour.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh142",
        "date": "2026-05-28",
        "title": "Library uploads no longer 413 at 50MB — nginx cap raised to 200MB",
        "highlights": [
            'The YunoHost nginx vhost capped library uploads at <span class="font-mono">client_max_body_size 50M</span>, so a single fixed-layout or illustrated epub above ~50MB was rejected with <span class="font-mono">413 Request Entity Too Large</span> before Django saw it. The cap now matches Django\'s <span class="font-mono">DATA_UPLOAD_MAX_MEMORY_SIZE</span> (200MB), which is the actual hard ceiling Yamtrack enforces. The SSO-bypass carve-out for <span class="font-mono">/webhook</span>, <span class="font-mono">/api/koreader</span>, and <span class="font-mono">/library/opds</span> stays at 50MB — those endpoints don\'t accept large bodies.',
            'Small <span class="font-mono">settings.py</span> cleanup along for the ride: <span class="font-mono">FILE_UPLOAD_MAX_MEMORY_SIZE</span> was being set twice (once env-configurable, once hardcoded 10MB further down silently overriding the first), so the env var had no effect. The duplicate is gone. The setting only governs the in-memory-vs-tempfile threshold and never affected upload size limits, but it was dead code that read like working knobs.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh141",
        "date": "2026-05-28",
        "title": "Reading hub: OPDS, library, KOReader, and Hardcover in one place",
        "highlights": [
            'Everything book-shaped — library uploads, the OPDS catalog URL, KOReader reading cadence / sessions / devices, and Hardcover sync state — now lives at <span class="font-mono">/reading/</span> under a new <strong>Reading</strong> entry in the sidebar Tools group (next to Music). The OPDS catalog URL is the first thing on the hub with a copy button, instead of being buried four screens down inside <span class="font-mono">Settings → Integrations</span>. The hub also renders a currently-reading rail, last-7-days cadence sparkline, "Stuck books" rail (in-progress with no activity for 30+ days), and recent reading sessions.',
            'The library browser at <span class="font-mono">/reading/library/</span> shows the OPDS URL inline (the old "settings → Integrations → OPDS catalog URL" pointer text is gone) and the four KOReader workspace pages (cadence / sessions / devices / unmatched) share a sibling tab strip so jumping between them no longer requires a bounce through the hub. The book list page at <span class="font-mono">/medialist/book</span> gets a small <span class="font-mono">Reading hub · Library · KOReader matching</span> chip strip — one click from tracking into any of the three flows.',
            'A new unified inbox at <span class="font-mono">/reading/unmatched</span> combines unmatched library files and unmatched KOReader document hashes onto one page behind <span class="font-mono">All · Library · KOReader</span> filter chips, so a user with both kinds of unmatched items can clear them out without page-bouncing. The link picker dropdowns are now ranked — in-progress books float to the top — same heuristic across all matching flows.',
            '<span class="font-mono">Settings → Integrations</span> kept only the credentials for Hardcover and KOReader (and a one-line pointer for Library + OPDS). The synced-books list, sub-page link strip, and unmatched-CTA banner all moved out. Book detail pages also pick up a small Hardcover push-status chip next to the existing KOReader summary when the user has connected Hardcover. <strong>Load-bearing URLs unchanged:</strong> <span class="font-mono">/library/opds/</span> (KOReader subscriptions) and <span class="font-mono">/api/koreader/...</span> (kosync wire protocol) keep their existing paths; legacy <span class="font-mono">/library/...</span> and <span class="font-mono">/koreader/...</span> browser paths 302-redirect to <span class="font-mono">/reading/...</span> so existing bookmarks still resolve.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh139",
        "date": "2026-05-27",
        "title": "Book Journey chart: hardened render + service-worker cache bump",
        "highlights": [
            'The ~ynh138 ship landed the Current Progress % fix but the Book Journey bar chart wasn\'t drawing on the deployed instance. Two fixes ship together in ~ynh139: the chart JS gets a more defensive Chart.js config (flat <span class="font-mono">borderRadius</span> on the delta segment, drop <span class="font-mono">borderSkipped: false</span>, clamp <span class="font-mono">delta_pct &gt;= 0</span>, run-on-DOMReady wrapper that also handles late-script loads), plus diagnostic <span class="font-mono">console.log</span> lines so future "chart didn\'t draw" reports are debuggable from a browser console alone.',
            'The service-worker cache <span class="font-mono">VERSION</span> bumps from <span class="font-mono">v3</span> → <span class="font-mono">v4</span>, which invalidates every <span class="font-mono">yamtrack-*-v3</span> cache on the next page load and forces a fresh fetch of all static assets. Heavy hammer, but reliable when the per-file mtime cache-buster doesn\'t bust an existing SW cache entry. After upgrading, the first page load may take a beat longer while the SW repopulates; subsequent loads are normal.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh138",
        "date": "2026-05-27",
        "title": "KOReader book history: real Current Progress %, Book Journey chart",
        "highlights": [
            'The <strong>Current progress</strong> headline on <span class="font-mono">/koreader/book/&lt;id&gt;/</span> was rendering <span class="font-mono">book.progress</span> (a page count) with a <span class="font-mono">%</span> suffix. A reader 71 pages into any book saw "71%" regardless of the book\'s length — coincidentally plausible at 100 pages, nonsense otherwise. The headline now comes from the actual kosync percentage the device last pushed (<span class="font-mono">mapping.last_percentage</span>, 0.0-1.0), with the page count surfaced as a small subtitle.',
            "The per-event scatter/line chart is replaced with a <strong>Book Journey</strong> stacked bar chart: one bar per inferred reading session (clustered from kosync events on a 30-minute idle gap), height = cumulative % at end of session, with a brighter top segment showing the % gained in that sitting. Tooltip carries the full date, start→end %, and session duration. Bars stay readable on phone-width canvases by spacing evenly rather than time-positioning — real-world gaps surface in the date labels instead.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh137",
        "date": "2026-05-27",
        "title": "OPDS catalog: six-shelf navigation root for KOReader",
        "highlights": [
            'The OPDS feed at <span class="font-mono">/library/opds/</span> used to hand KOReader a single flat acquisition list of every uploaded book, newest-first. Once the library grew past ~30 titles that was unbrowseable on the device. ~ynh137 switches the root to a navigation feed with six shelves: <strong>Up Next</strong> (linked Books currently In Progress), <strong>Want to Read</strong> (Planning status), <strong>Recently Added</strong> (newest 50 uploads), <strong>By Author</strong> (nav feed → per-author acquisition feed), <strong>Unmatched</strong> (files not yet linked to a tracked Book), and <strong>All Books</strong> (the original flat list, kept as a fallback).',
            'KOReader caches OPDS pages aggressively, so the next time you open the catalog after upgrading it should re-pick the feed and render with the new nested layout. All shelf links carry an <span class="font-mono">rel="up"</span> back-reference so KOReader\'s back button works on older firmware that doesn\'t auto-derive it. Auth, the HEAD-handshake, telemetry logging, and the <span class="font-mono">/library/opds/file/&lt;pk&gt;</span> download path are unchanged.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh136",
        "date": "2026-05-27",
        "title": "KOReader OPDS finally works: SSOWAT was stripping the Basic header",
        "highlights": [
            'The real root cause behind ynh132-ynh135: <strong>YunoHost\'s SSOWAT layer clears incoming <span class="font-mono">Basic</span> Authorization headers</strong> by default on every app permission, as a "spoofing protection" — apps are assumed to trust only YNH-validated identity. The OPDS catalog endpoint explicitly <em>wants</em> the Basic header (KOReader\'s API token), and Yamtrack validates it itself, so we need to opt out via <span class="font-mono">protect_against_basic_auth_spoofing = false</span> on the api permission. Without that, KOReader was sending the Authorization header on every request and SSOWAT was clearing it before nginx even forwarded the request to gunicorn — explaining why the server\'s telemetry kept logging "no Authorization header" no matter what we tried client-side.',
            "Same root cause as why Audiobookshelf / Kavita / Nextcloud's OPDS catalogs work on YunoHost — their packages disable this protection on their respective api permissions. ~ynh136 declares it in manifest.toml (clean path) and also writes the override into <span class=\"font-mono\">/etc/ssowat/conf.json.persistent</span> from the install / upgrade scripts as a runtime safety net for older YunoHost versions that ignore unknown manifest keys. Telemetry from ynh135 stays in place for now; it'll be cleaned up in a follow-up ship once the fix is confirmed in real KOReader usage.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh135",
        "date": "2026-05-27",
        "title": "OPDS auth telemetry for KOReader debugging",
        "highlights": [
            'Diagnostic ship: the OPDS basic-auth handler now logs structured "OPDS-AUTH:" lines to the journal recording header presence, length, scheme, decoded username, and password length — never the password itself. Lets us see exactly what KOReader is (or is not) sending without resorting to packet capture. Safe to ship on a single-user fork; on a multi-user instance we\'d want to gate this behind DEBUG since the username is logged.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh134",
        "date": "2026-05-27",
        "title": "OPDS Authorization header now reaches Django (KOReader auth works end-to-end)",
        "highlights": [
            'The ynh133 fix made HEAD reach the catalog, but KOReader\'s Basic auth still bounced at 401 — YunoHost\'s plain <span class="font-mono">proxy_params</span> nginx snippet (which our public-endpoint carve-out uses) does not explicitly forward the <span class="font-mono">Authorization</span> header. KOReader was sending credentials, nginx was swallowing them before Django saw them, and the basic-auth handler always read an empty header → 401. ~ynh134 adds <span class="font-mono">proxy_set_header Authorization $http_authorization;</span> to the carve-out so the header survives the proxy hop. kosync uses custom <span class="font-mono">x-auth-*</span> headers that nginx forwards by default, which is why kosync was unaffected.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh133",
        "date": "2026-05-27",
        "title": "OPDS endpoints accept HEAD so KOReader's auth handshake completes",
        "highlights": [
            'Hotfix for KOReader on the ynh131/ynh132 OPDS feature: KOReader\'s catalog browser issues a <span class="font-mono">HEAD</span> request before sending Basic auth (to discover the <span class="font-mono">WWW-Authenticate</span> realm), but the OPDS endpoints were decorated with <span class="font-mono">@require_GET</span> and rejected HEAD with a 405. Some clients fall through to an unauthenticated GET on a 405 and report "authentication required" without ever trying credentials. ~ynh133 widens the OPDS endpoints to <span class="font-mono">["GET", "HEAD"]</span>; Django strips the body from HEAD automatically so the headers (including WWW-Authenticate on 401) still go through unchanged.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh132",
        "date": "2026-05-27",
        "title": "OPDS endpoint reachable on YunoHost installs (SSO carve-out)",
        "highlights": [
            'Fixes the ynh131 OPDS feature on YunoHost installs: the SSO layer was 302-redirecting unauthenticated requests to <span class="font-mono">/library/opds/</span> before Yamtrack\'s HTTP-Basic handler could run, so KOReader\'s OPDS browser saw a login page instead of the catalog. ~ynh132 adds <span class="font-mono">/library/opds</span> to both the nginx regex carve-out and the YunoHost <span class="font-mono">api</span> permission allowlist (same pattern as the existing <span class="font-mono">/api/koreader</span> kosync carve-out), so KOReader can authenticate with its own credentials.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh131",
        "date": "2026-05-27",
        "title": "OPDS server + library uploads for friction-free KOReader auto-bind",
        "highlights": [
            'New <strong>/library</strong> page: upload your <span class="font-mono">.epub</span> files (one at a time, or as a <span class="font-mono">.zip</span> archive that Yamtrack walks recursively for epubs inside) and Yamtrack hosts them for your KOReader devices. Each upload extracts title/author/language/cover/ISBN from the OPF, and when exactly one tracked Book in your library has the same title the file is auto-linked to it — no manual binding required.',
            'New <strong>OPDS catalog</strong> at <span class="font-mono">/library/opds/</span>, exposed via the existing Yamtrack integration token (HTTP Basic; same username + API token as kosync). Add it to KOReader (<span class="font-mono">File browser → Search → OPDS catalog → +</span>) and your uploaded books appear alongside the rest of your KOReader library. Downloads land on the device under a canonical filename Yamtrack pre-computed at upload time.',
            '<strong>100% kosync auto-bind</strong> for OPDS-side-loaded books. Because Yamtrack chose the filename, it already knows <span class="font-mono">md5(&lt;canonical-filename&gt;)</span> at upload — the next kosync push for that hash binds directly to the matched Book without ever passing through <strong>/koreader/unmatched</strong>. Works when KOReader is in filename-hash mode (the OPDS download is a fresh copy KOReader will hash by its basename).',
            "Per-file actions in the library browser: rename the canonical filename (which rotates the kosync auto-bind hash — be sure to re-download on KOReader after renaming), manually link to a tracked Book when title-match was ambiguous, or delete. Cover images are extracted from the epub OPF and rendered inline so the browser doubles as a small bookshelf.",
            "Non-epub files (PDF, CBZ, CBR, MOBI, etc.) are silently skipped from bulk uploads for this ship — adding more formats means writing per-format metadata extractors and reasoning about how KOReader hashes them, which is queued as a follow-up. Single uploads in non-epub formats are rejected.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh130",
        "date": "2026-05-27",
        "title": "KOReader: auto-bind by filename when KOReader is in filename-hash mode",
        "highlights": [
            "If you've set KOReader's kosync plugin to <strong>filename-mode</strong> document hashing (the alternative to the default binary-mode), Yamtrack now auto-binds incoming sync hashes to your tracked books with zero manual linking. On every kosync PUT we check whether <span class=\"font-mono\">md5(&lt;title&gt;.epub)</span> for any book in your library equals the incoming hash — if it does, the mapping is bound silently and the percentage replays onto the book exactly as if you'd linked it by hand.",
            'Works retroactively too: any pre-existing unmatched mappings on your account will get auto-bound on the next sync from KOReader. The <strong>/koreader/unmatched</strong> page also surfaces per-row filename matches in green when found, alongside the existing "only In-progress book" suggestion in indigo. When neither match exists but you have one In-progress book without a mapping, the page now also tells you the exact filename to rename to (<span class="font-mono">&lt;title&gt;.epub</span>) so the next sync auto-binds.',
            'Match algorithm tries a small set of filename variants per book: the title with .epub / .pdf / .cbz / .cbr / .mobi / .azw3 / .fb2 extensions, plus a lowercased variant. Match is exact (KOReader sends the basename verbatim, no case-folding) so files with author or series in the filename still won\'t auto-match — for those, rename in KOReader to the canonical <span class="font-mono">&lt;title&gt;.&lt;ext&gt;</span> form. Manual links are never overridden by an auto-bind guess.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh129",
        "date": "2026-05-26",
        "title": "KOReader: reading-time stats everywhere",
        "highlights": [
            "Reading time (in hours/minutes) now surfaces across all the KOReader pages, derived from inferred session durations. <strong>/koreader/cadence</strong> gains three cards below the streak/active-days row: total reading time over the 53-week window, average session length, and minutes per active day. <strong>/koreader/sessions</strong> gains headline cards for total time read, session count, and average session length (the table itself stays capped at 200 rows; the totals are computed across every session so heavy readers' all-time totals don't truncate as the table paginates).",
            'Per-book history page (<strong>/koreader/history/&lt;book&gt;</strong>) gains a fifth stat card showing total reading time for that specific book — so you can answer "how many hours did I spend on this one" without opening a calculator. The book detail page\'s KOReader summary card (next to Notes) also gains a "Xh read" badge alongside the existing percentage and last-sync info.',
            "All time figures come from the same noise-filtered session list the rest of the KOReader UI uses (30-minute idle gap or book change closes a session; sub-minute single-event pings are dropped), so the numbers stay consistent across every view.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh128",
        "date": "2026-05-26",
        "title": "KOReader: book-detail summary card + smarter unmatched picker",
        "highlights": [
            "Book detail pages now show a compact <strong>KOReader</strong> card when a KOReader sync is bound to the book — last percentage, last device, time since last sync, total event count, and the three most recent inferred reading sessions inline. The full per-book timeline is still one click away via the ``Full history →`` link on the card (same destination as the previous standalone link, which the card replaces).",
            "<strong>Unmatched documents picker</strong> at ``/koreader/unmatched`` now ranks your library books smartly: In-progress books without a KOReader mapping float to the top, then other In-progress books, then everything else alphabetical. When there's exactly one strong candidate, the dropdown is pre-selected to that book and a ``Likely match: <title>`` chip appears above the form — so the common case (\"this hash is the book I'm reading right now\") becomes one click instead of scrolling the alphabet.",
            "The kosync wire protocol still only sends the file md5 (no title/author/ISBN), so a perfect auto-match needs the OPDS-server feature; until then, this ranking eliminates 80% of the friction with a single sort change.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh127",
        "date": "2026-05-26",
        "title": "KOReader: reading cadence heatmap + inferred sessions",
        "highlights": [
            'New page: <strong>Reading cadence</strong> at ``/koreader/cadence`` (linked from the integrations card alongside Devices). Renders a GitHub-style 7x53 contribution grid for the last 53 weeks, with each cell coloured by the day\'s positive forward progress summed across all your KOReader-synced books. One full "book-unit" per day is the heaviest shade. Headline cards above the grid show active days, current/longest reading streak, total progress over the window, and the biggest single day. Re-reading earlier chapters never subtracts (max-minus-min per (day, book) is clamped to positive), so a partial re-read still reports as a zero-delta day rather than going negative across midnight.',
            "New page: <strong>Reading sessions</strong> at ``/koreader/sessions`` (also linked from the integrations card). Groups consecutive KOReader syncs into inferred sessions — a new session opens after a 30-minute idle gap, or when you switch to a different book. Each row shows start/end, duration in minutes, percent progress made within the session, the book, and the underlying event count. Sessions that are both shorter than a minute and only one event (KOReader's book-open ping) are dropped, while a long single-event session is kept.",
            'Same sessions table also surfaces below the per-book history chart at ``/koreader/history/<book>`` — "book details once attached" — so you can see exactly when you sat down with a specific book without leaving its detail view.',
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh126",
        "date": "2026-05-26",
        "title": "KOReader: dedicated page for unmatched documents",
        "highlights": [
            "Unbound KOReader documents (file hashes that haven't been linked to a tracked book yet) now live on a dedicated <strong>/koreader/unmatched</strong> page instead of mixing into the Synced-books list on the integrations settings card. Fixes a layout bug where the inline ``Select a book…`` dropdown's width was squeezing the flex sibling to ~16px wide, causing the 32-character document hash to render one character per line. The integrations card surfaces a clickable ``N unmatched documents waiting to be linked →`` badge when there's anything outstanding.",
            "Note on auto-matching: the kosync protocol only sends the file's md5 hash, not title/author/ISBN, so Yamtrack genuinely can't auto-bind hashes to books without seeing the file itself. The proper fix for that is the planned OPDS-server feature (host the epub, parse OPF metadata at upload, know the hash→book mapping before any sync arrives). Until then, the linking flow stays manual but now in a layout that actually fits on screen.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh125",
        "date": "2026-05-26",
        "title": "KOReader visibility: per-book reading timeline + devices dashboard",
        "highlights": [
            "Each KOReader sync now appends to an append-only event log (``KOReaderProgressEvent``) alongside the existing mapping-row upsert, so the full per-push history (timestamp, percentage, device, page) is preserved instead of being overwritten. No change to the kosync wire protocol — your KOReader plugin keeps pushing exactly as before.",
            "New page: <strong>KOReader reading history</strong> on each book's detail page (when there's at least one sync event), showing a percentage-over-time chart with one line per device — hover for the exact page/time/percentage. Surfaced as a small ``KOReader reading history →`` link on the book detail page, right below your notes section.",
            "New page: <strong>KOReader devices</strong> at ``/koreader/devices`` (linked from the Integrations settings page next to the KOReader Progress Sync header). Lists each device that has ever synced for your account with last-seen, sync count, distinct books touched, and the most-recent book — useful when you switch between, say, a Kindle and a Kobo and want to see which one has the latest progress.",
            "Both views are user-scoped: the timeline 404s if you try to load another user's book, and the devices view only aggregates your own events.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh124",
        "date": "2026-05-26",
        "title": "Integrations page shows the correct kosync server URL",
        "highlights": [
            "Fixed the ``URLS`` env var being templated without the app's path prefix on YunoHost installs at a non-root path (e.g. ``/yamtrack``). Symptom: the integrations page's auto-generated KOReader server URL was missing the path, so anyone who copy-pasted it into KOReader got SSO-302'd at ``/api/koreader/...`` instead of the working ``/yamtrack/api/koreader/...``. Same template builds OAuth redirect_uri values for Trakt / Simkl / AniList, so this also unblocks the public-mode OAuth flows on sub-path installs. ~ynh124 fixes the template (``URLS=https://__DOMAIN____PATH__``) and adds a one-time migration in the upgrade script that rewrites the line on existing installs whose ``.env`` still has the old shape.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh123",
        "date": "2026-05-26",
        "title": "KOReader sync: case-insensitive username matching",
        "highlights": [
            "Fixed KOReader sync silently failing on accounts whose Yamtrack username has any uppercase letters. KOReader's kosync plugin lowercases the configured username before sending it in the ``x-auth-user`` header, but Yamtrack was doing a case-sensitive ``User.objects.get(username=...)`` lookup — so a user typed as ``Luke`` in KOReader arrived as ``luke`` on the server, missed the actual ``Luke`` account, and returned ``Unauthorized user`` (which KOReader surfaces as ``Unknown server error`` on the Register flow and ``Unauthorized user`` on the Login flow). ~ynh123 enumerates candidate users case-insensitively and uses ``md5(user.token)`` as the tie-breaker, so installs with multiple users whose names differ only by case still resolve unambiguously to the correct account. Both ``/api/koreader/users/auth`` and ``/api/koreader/users/create`` got the fix; any users whose Yamtrack name was already all-lowercase weren't affected.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh122",
        "date": "2026-05-26",
        "title": "Public API endpoints actually reach Django (KOReader, ListenBrainz, webhooks)",
        "highlights": [
            "Fixed the ``/yamtrack`` URL prefix not being stripped before the SSO-bypass carve-out forwards to Django, which was making /api/koreader, /api/scrobble (ListenBrainz), and /webhook/{jellyfin,plex,emby} silently 404. The carve-out's nginx ``location`` is a regex location, and a regex location can't use the trailing-slash trick the UI block uses to strip the app prefix — so requests like ``/yamtrack/api/koreader/users/auth`` were being passed through unchanged, and Django (whose routes don't include the ``/yamtrack`` prefix) had no idea what to do with them. The SSO bypass itself was working; the URL just never landed on a registered route. ~ynh122 strips the prefix via a captured group in ``proxy_pass`` (allowed inside regex locations; doesn't mutate ``$uri`` the way a ``rewrite`` would, so SSOWAT's allowlist check at the access phase still sees the original ``/yamtrack/...`` URI and lets the request through). The ListenBrainz scrobble endpoint and the media-server webhooks were broken the same way and are also fixed.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh121",
        "date": "2026-05-26",
        "title": "KOReader sync + reliable YunoHost upgrades",
        "highlights": [
            "KOReader sync: Yamtrack now speaks the kosync protocol at /api/koreader, so KOReader on your e-reader can push reading progress (current page, percent, document hash, device) without going through SSO. Configure it under Settings → Integrations → KOReader.",
            "KOReader UI enrichments on the integrations page: each recent sync shows the book cover, an In-progress / Completed status pill, current page, the device that sent it, and a relative-time stamp — so you can confirm a sync landed without leaving the page.",
            "YunoHost upgrades now reliably refresh the API permission allowlist so /api/koreader is publicly reachable on existing installs. After several iterations (~ynh116..120) that each hit a different version-skew between the raw ``yunohost user permission`` CLI and what the installed host actually accepted, the upgrade script now calls the packaging helpers ``ynh_permission_url --add_url`` and ``ynh_permission_update --add`` (helpers v2.1) — these wrap whatever syntax the local YunoHost supports. ~ynh120 was the first version where the upgrade ran without warnings on the raw CLI, but the helper itself was called with the fully-qualified ``$app.api`` permission name (the helpers internally re-prepend ``$app``, producing ``yamtrack_fork.yamtrack_fork.api`` and crashing inside ``permission.py``); ~ynh121 passes just ``api`` and finally lands the change.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh112",
        "date": "2026-05-25",
        "title": "PWA upgrade: offline, install, push, sync",
        "highlights": [
            "Offline fallback: pages you've visited recently render straight from cache, and a dedicated offline page appears for routes the cache hasn't seen. Service worker now uses per-strategy caches (NetworkFirst for navigations, CacheFirst for static and posters) instead of a single bare cache.",
            "Safer SW updates: a new version no longer activates mid-session and replace assets under your feet. When a new SW is waiting, a 'New version available — Reload' toast appears in the corner. Click it to apply.",
            "App-icon badge now combines today's airing releases with unread What's New notes. Refreshes after every HTMX action (rating, status toggle) and when you return to the tab — so the badge tracks the real number, not just a yes/no for unread notes.",
            "Custom install prompt: a download icon appears next to the bell when the browser thinks Yamtrack is installable. One tap → install. iOS Safari is unchanged (Add to Home Screen there is a manual flow).",
            "Web Push notifications (opt-in per device): Settings → Notifications has a new card. Enable on this device, and release alerts arrive as OS-level push notifications even when the tab is closed. Existing Apprise URLs keep working alongside push; per-show exclusions apply to both channels. Requires the server admin to set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY.",
            "Offline write queue: if you mark something watched or change a status while offline, the change is held in IndexedDB and replayed automatically when you reconnect. A small 'N queued' chip appears in the header while items are pending; a toast confirms when the queue drains. Chromium also runs the drain via Background Sync even with the tab closed.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh106",
        "date": "2026-05-25",
        "title": "Fix leaked comment in track modal",
        "highlights": [
            "Fixed a multi-line {# ... #} comment in the track-modal template that was rendering as visible text under every form field — same Django template gotcha that bit the Browse page in ynh102 (single-line only; switched to {% comment %} which handles multi-line cleanly).",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh105",
        "date": "2026-05-25",
        "title": "Quick-fill 'Today / Release date' on track form",
        "highlights": [
            "Added 'Today' and 'Release date' (or 'Air date' for TV / anime) quick-fill chips under the Start date and End date inputs in the track modal. Mirrors the affordance the episode tracker already had, now available for movies, TV, anime, manga, games, books, comics, board games, and records.",
            "Release date is pulled from each provider's metadata (TMDB release_date / first_air_date, Discogs released, etc.) and slotted into the date input — works for both DateInput and DateTimeInput forms (datetime gets a T00:00 suffix).",
            "Chip only renders when the provider actually returned a parseable date, so older imports or sparse providers don't show an empty button.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh104",
        "date": "2026-05-25",
        "title": "Browse language filter: hide Hindi only",
        "highlights": [
            "Flipped the Browse language filter from an English/Japanese allowlist to a Hindi-only blocklist — Hindi titles flooding the discovery feed was the actual problem; everything else (Korean, French, Spanish, etc.) now passes through by default.",
            "Toggle button reads 'Hindi hidden' / 'All languages' to match.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh103",
        "date": "2026-05-25",
        "title": "Japanese in default Browse languages + comment fix",
        "highlights": [
            "Default Browse language allowlist now includes Japanese (anime) alongside English. The toggle button reads 'EN / JA only' / 'All languages' to match.",
            "Fixed a stray Django template comment that was rendering as visible text above the language toggle ('{# English-only filter toggle... #}'). Django's {# ... #} only works on a single line; switched to {% comment %} which handles multi-line.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh102",
        "date": "2026-05-25",
        "title": "English-only Browse filter by default",
        "highlights": [
            "Browse now hides movies / TV whose TMDB original language isn't English by default — keeps the discovery feed focused on titles you can immediately watch instead of being dominated by anime / K-drama / Bollywood results that bubble up high in 'popular'.",
            "Added an 'English only / All languages' toggle button in the Browse header. One click flips the preference; it's remembered per user.",
            "Applies to TMDB sources only (Trakt and other sources don't expose original_language consistently). The filter passes through tiles missing the field rather than dropping them.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh101",
        "date": "2026-05-25",
        "title": "% match badges + 'For You' Browse category",
        "highlights": [
            "Each Browse tile (TMDB movies/TV) now shows a personal '% match' badge based on a per-user taste profile — weighted genre bags built from your rated/completed items (positive) and your dismissed/dropped items (negative). Color-coded green ≥80, amber ≥60, muted below.",
            "Added a 'For You' category at the top of the Browse tabs. It pulls a candidate pool from Popular + Top Rated + Trending, drops items you've already tracked or dismissed, scores them against your taste profile, and shows the top matches by descending score. Falls back to the regular Popular list when you don't have enough rated items yet (currently 5).",
            "Badges hide on tiles you've already engaged with (status chip wins that real estate), and on cold-start users (fewer than 5 rated items) until the signal is meaningful.",
            "Taste profiles are cached per (user, media_type) for 24h and automatically invalidated whenever you save a score, complete an item, dismiss something, or change a status — so changes show up on the next Browse load.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh100",
        "date": "2026-05-25",
        "title": "Mobile-tappable dismiss button",
        "highlights": [
            "Added an always-visible 'X' button in the top-left of each Browse tile (grid view) for items that aren't already in your library. The kebab menu it lived in was hover-only, so touch devices couldn't reach 'Not interested' — this button is tappable directly.",
            "Doesn't render when the tile is already tracked (the status chip lives in the same corner, and dismissing something you're already engaging with doesn't make sense).",
            "List-view layout already had a dedicated dismiss button in the action row, so no change needed there.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh99",
        "date": "2026-05-25",
        "title": "'Not interested' on the Browse page",
        "highlights": [
            "Every tile on the Browse page now has a 'Not interested' option in its kebab menu (grid view) or a circle-X button next to the action pills (list view). Click it and the tile disappears with a soft fade and won't come back on future visits.",
            "Dismissals persist per user, scoped to (source, media_type, media_id), and apply to both TMDB and Trakt source modes.",
            "Stored as data we can mine later — the 'not interested' signal is just as useful for personalization as the 'completed/loved' signals, so the table is set up to feed future recommendation tweaks.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh98",
        "date": "2026-05-25",
        "title": "Reliable discography images + artist search",
        "highlights": [
            "Album covers in the 'More by artist' section (record page) and the artist discography page now use Discogs' search-by-artist cover URLs, which populate reliably — the previous /artists/<id>/releases 'thumb' field was empty for most entries, so most tiles fell back to monogram placeholders.",
            "Record pages now resolve the artist via the canonical Discogs artist ID embedded in the release metadata, not a fuzzy name search — so the section shows up reliably even for artists with disambiguation suffixes like 'Beyoncé (2)' that previously confused the lookup.",
            "Music search now surfaces matching artists at the top of the record results: type an artist name in the search bar with type=Records and you'll see clickable artist chips (avatar + name) that open the full discography page — no longer need to own one of their records first.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh97",
        "date": "2026-05-25",
        "title": "Discography on the record page",
        "highlights": [
            "Record detail pages now include a 'More by <artist>' section under the listening stats: up to 12 other Discogs releases by the same artist, with an emerald 'Owned' badge on the ones you already track and a click-through to the existing record detail page.",
            "A 'See all on artist page →' link in the section header opens the full Discogs discography page (introduced in ynh96) with filters for 'In your library' / 'Not in your library' / 'All' and sorts by year or title.",
            "Artist names in the 'ARTIST' row of a record's Details are clickable too — each credited artist links to their own discography page.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh96",
        "date": "2026-05-25",
        "title": "Artist discography page",
        "highlights": [
            "Click the artist name on any record detail page to open a new artist page (Discogs-backed) showing the full discography, sorted by year with title fallback. Multiple credited artists each link to their own page.",
            "Releases you already track are flagged with an emerald 'Owned' badge and link straight to the existing record detail page; the header shows total releases, library overlap count, and a coverage percentage.",
            "Filter the grid by 'In your library', 'Not in your library', or 'All', and sort by newest / oldest / title.",
        ],
        "fixes": [],
    },
    {
        "version": "0.25.2~ynh89",
        "date": "2026-05-24",
        "title": "Where to watch, in the hero",
        "highlights": [
            "Streaming providers on movie and TV detail pages moved out of the buried 'Details' section and into the hero, right under the score pills, with a 'Streaming in <region>' label so you can see at a glance whether the title is available where you actually watch.",
            "Each provider chip is now clickable — it deep-links into the JustWatch listing for the title in your region, so one tap takes you from 'should I add this?' to 'here it is on Netflix'.",
            "Empty states are clearer: 'Not streaming in <region> right now' when no flatrate/free providers exist, instead of the previous bare 'No watch providers' line.",
        ],
        "fixes": [],
    },
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
