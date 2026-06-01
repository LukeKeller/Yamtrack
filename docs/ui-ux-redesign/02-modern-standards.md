# 02 — Modern standards & competitive scan

Conventions used by the leading apps in each adjacent category, and
the patterns Stackwise should adopt, adapt, or skip.

## Comparison set

Media tracking is a fragmented space. Stackwise is unusual in covering
nine media types in one app — most competitors specialize. The
comparison below pulls from:

| App | Strength | Why it matters here |
| --- | --- | --- |
| **Letterboxd** | Movie tracking, score precision, lists, social | Best-in-class detail page + half-star scoring + lists |
| **Trakt** | TV-first, calendar, integrations | Closest peer in scope; canonical calendar + scrobble integrations |
| **AniList** | Anime/manga + community, customization | Custom themes, list view density, profile pages |
| **Plex** / **Jellyfin** | Media server library UI, hero/backdrop art | Hero/backdrop pattern, "continue watching" surface |
| **Backloggd** | Games tracker, social, lists | Status semantics for games, log entries as activity |
| **HowLongToBeat** | Game completion time | Source of "time-to-beat" expectation |
| **StoryGraph** / **Goodreads** | Book tracking, stats narrative | Wrapped-style year recap, reading goals |
| **Discogs** | Vinyl collection | Collection-as-database UX |
| **Linear** / **Notion** / **Vercel** | Productivity UX | Command palette, keyboard-first, density |

What follows is a pattern-by-pattern audit: what the leaders do, what
Stackwise does, and the proposed direction.

## 1. Detail-page hero

**Convention.** A 16:9 backdrop image filling the top quarter to half
of the viewport, with a gradient fade to the page background. Poster
overlays the bottom-left of the hero; title, year, runtime, and a
primary CTA sit to the right of (or below) the poster. Reduced or
absent backdrop for media types without backdrop art (books, board
games) — fall back to a stretched, blurred poster as a hero.

**Where it's used.** Letterboxd, Trakt, Plex, Jellyfin, Backloggd,
AniList, IMDb. It's the single biggest visual difference between a
"this is a media app" and "this is an admin tool".

**Stackwise today.** No backdrop. Poster is 1/4 of the page width on
desktop, sitting in a flat slate column.

**Proposed adoption.** Add a `media.backdrop` field (most TMDB / IGDB
responses include it; fallback chain: backdrop → blurred poster →
gradient). Render a 16:9 hero on movie/TV/anime/game pages; fall back
to a colored gradient hero on books/board games using the dominant
poster color (via a tiny `prominent-color` script or a server-side
hash-to-hue).

The mock at `mocks/media-details-movie.html` demonstrates the hero +
content composition.

## 2. Primary action: single, decisive

**Convention.** Most modern trackers boil a media's primary action
down to **one** verb: "Mark watched", "Add to watchlist", "Add to
library". Secondary actions live in a kebab/overflow menu. Status is
displayed as a pill or chip, not as a button.

**Stackwise today.** Three colored buttons (Track / Lists / History) of
equal visual weight on cards and detail pages. The "Track" button has
edit-pencil + chevron + status text all bundled.

**Proposed adoption.** One primary button reading the current status
(or "Add to library" if untracked). Click → status sheet with the 5
states. Long-press / kebab → overflow menu with Lists, History, Sync,
Share, Delete. The track-modal becomes a drawer for "edit all fields"
flow — a power-user surface, not the default.

See `mocks/track-drawer.html`.

## 3. Score input: half-stars or 5-with-precision

**Convention.** 5-star with halves is the modern norm (Letterboxd,
Plex). Goodreads / StoryGraph stick to 5 whole stars. AniList lets the
user pick scoring scale (5-pt, 10-pt decimal, 100-pt) — most
configurable.

**Stackwise today.** 10-pt integer scoring, displayed as one star
glyph + the number. Editor is a row of 10 star buttons with the
numerals 1-10 underneath.

**Proposed adoption.** Keep 10-pt internally (it's the data model)
but render as 5 stars-with-halves in the UI. Hover over a star shows
the half-position cursor; click commits. Power users who want
fractional precision can use the underlying number input in the track
drawer.

## 4. Status as semantic pill

**Convention.** Status (Completed / In progress / Planning / Paused /
Dropped) is rendered as a colored pill or chip. Color is consistent
across every appearance — same green for completed in the list, on the
card, on the detail page.

**Stackwise today.** Status colors are defined (`status_color`
template tag) but they're applied to icon strokes, not to backgrounds
or pills. Status on cards is a `bg-gray-900/90` badge with the colored
SVG inside — the color is barely visible.

**Proposed adoption.** Pills with semi-transparent fill (`bg-emerald-500/15`
+ `text-emerald-300`) for legibility on every surface. Status sheets
animate between states with a 150 ms color shift.

See `mocks/_assets/tokens.css` for the status palette.

## 5. Continue / Up next

**Convention.** Plex and Jellyfin lead with "Continue watching".
Trakt's home is "Up next" — a list of the next unwatched episode per
in-progress show. Backloggd has "Currently playing" with last-save
date.

**Stackwise today.** The home page lists in-progress media but doesn't
say "what's the *next thing to do*". For a TV show you have to drill
into the season page to see which episode is next.

**Proposed adoption.** A "Up next" carousel above "In progress",
showing one card per in-progress show/manga/game with the next
episode/chapter/save and a +1 button.

See `mocks/home.html`.

## 6. Activity / recent

**Convention.** GitHub-style "activity feed" or a "recently completed"
strip. Letterboxd's "Recent activity" is sit-down content; Trakt has a
last-watched feed; AniList has a per-user activity wall.

**Stackwise today.** simple-history records every change but nothing
surfaces it. The closest is the statistics-page "timeline" view which
groups by month/year and is calendar-shaped, not feed-shaped.

**Proposed adoption.** A compact "Recent activity" rail on home: "You
marked X completed yesterday", "Y aired today", "Z arrived in your
calendar". One line per event, max 7 items. Click-through to the item.

## 7. Calendar density

**Convention.** Calendar apps default to grid for desktop, agenda
(list) for mobile. Trakt also offers a "premiere only" filter.

**Stackwise today.** Both views are user-selectable on every viewport.
The grid view on mobile gets vertical-cramped.

**Proposed adoption.** Auto-select agenda for mobile, grid for
desktop. Filter chips (movies / TV / anime / premieres). Tap-to-jump
on grid cells.

## 8. Lists with cover mosaics

**Convention.** Letterboxd, AniList, Steam — all use 4-up cover
mosaics (or 2x2 cover collages) for list previews when no list cover
art is set. Communicates "what's inside" instantly.

**Stackwise today.** Single cover image (uploaded by user, falls back
to a generic placeholder).

**Proposed adoption.** When `custom_list.image == IMG_NONE`, render a
2x2 grid of the first 4 items' posters as the cover.

## 9. Stats as narrative / wrapped

**Convention.** Spotify Wrapped invented the category. Letterboxd's
year-in-review and StoryGraph's monthly stats followed. The narrative
pattern: one card per insight, full-screen, swipeable.

**Stackwise today.** Statistics is a chart wall. Good charts, but a wall.

**Proposed adoption.** Keep the chart wall at `/statistics`. Add a
`/statistics/recap/<year>` view that wraps the same data into a
ten-card narrative ("you watched 142 movies", "your average score was
7.3", "your most-watched genre was…", "your longest streak was 23
days"). Cards stack vertically on mobile, side-by-side on desktop. The
data backend doesn't change — only the presentation.

## 10. Command palette (⌘K)

**Convention.** Press ⌘K (or Ctrl-K) anywhere to open a fuzzy command
palette. Linear / Notion / Vercel / GitHub / Raycast. Lets power users
move through the app without sidebar clicks.

**Stackwise today.** No palette. Only `/` to focus search.

**Proposed adoption.** A ⌘K palette with:

- **Search.** Live, debounced, results inline (movies/TV/anime/etc.).
  Pressing Enter on a result opens its detail page; pressing space + a
  status key marks it directly (`w` = watched, `p` = planning).
- **Jump.** "Home", "Calendar", "Lists", "Settings", every media-type
  list, every saved view.
- **Actions.** "Switch theme", "Start a Trakt import", "Today's
  releases", "Toggle density".

The mock at `mocks/command-palette.html` shows the visual.

## 11. Bottom navigation on mobile

**Convention.** iOS Mail, Spotify, Plex, Trakt mobile — all use a
bottom nav for 4-5 primary destinations. Self-hosted PWA installs
benefit specifically because users add the app to the home screen and
expect native-style navigation.

**Stackwise today.** Sidebar via hamburger only. No bottom nav. No
gestures.

**Proposed adoption.** A 5-item bottom nav on mobile (`< lg`): Home,
Discover, Search, Lists, Profile. Sidebar still accessible by tapping
the avatar in the top-right of the top bar (which opens a slide-in
sheet with the full nav and settings).

See `mocks/mobile-home.html`.

## 12. Bottom-sheet modals on mobile

**Convention.** iOS-style bottom sheets are the modern mobile dialog.
They preserve context (the page is still partly visible), they're
thumb-friendly (controls at the bottom), and they support gesture
dismiss (swipe down).

**Stackwise today.** All modals are centered overlays — same on
desktop and mobile.

**Proposed adoption.** Detect viewport width in the modal CSS — on
`< md` viewports, the modal slides up from the bottom and fills 90 % of
the height. On `≥ md` it stays centered.

## 13. Discoverable density toggle

**Convention.** Gmail, Linear, GitHub Projects — all expose a
density toggle (Comfortable / Compact / Cozy). Some auto-detect by
collection size.

**Stackwise today.** None. The grid is one size.

**Proposed adoption.** A simple user pref + toggle button in the
filter bar. The grid responds via `data-density="compact|comfortable"`
and CSS variables on the grid template.

## 14. Color-coded media-type accents

**Convention.** AniList tints each media-type tab with a different
hue. Trakt does it for sub-modes (TV blue, movies green). The
discriminator is small (~10% saturation increase on a colored stripe
or border) but it tells the eye where it is.

**Stackwise today.** All media types use the same indigo accent.

**Proposed adoption.** Each media type gets a tertiary accent for
edges, badges, and the active sidebar state:

| Type | Hue |
| --- | --- |
| TV | sky-500 |
| Movie | blue-500 |
| Anime | pink-500 |
| Manga | violet-500 |
| Game | emerald-500 |
| Book | amber-500 |
| Comic | orange-500 |
| Board game | lime-500 |
| Record | rose-500 |

Used sparingly: 2-px left border on detail-page hero, small dot in
sidebar nav, tinted progress bar on cards. The primary `indigo-500`
brand color is preserved for CTAs.

## 15. Skeletons & progressive loading

**Convention.** Modern lists fade in skeleton boxes during fetch, then
swap to real content. HTMX-first apps still benefit — the `htmx-request`
class can drive `animate-pulse` skeletons during a swap.

**Stackwise today.** Spinning circle indicators. lazysizes places a
solid gray placeholder for images.

**Proposed adoption.** A `.skeleton` class with `animate-pulse` and a
shimmer; HTMX `hx-indicator="..."` targets render skeletons during
swaps; image placeholders gain the shimmer too.

## 16. Inline import progress banner

**Convention.** Spotify and Apple Music both show a persistent banner
at the top of the screen while a large operation runs.

**Stackwise today.** The import is fire-and-forget; the user has to
revisit the import page to see status.

**Proposed adoption.** Detect a running TaskResult on every page load
(or via HTMX poll) and render a slim banner at the top: "Importing
from Trakt — 142/280 …" with a click-through to the import page. Hide
once it completes.

## 17. Accessible focus rings

**Convention.** A visible `focus-visible:ring-2` style on every
interactive element, with `focus-visible` (not just `focus`) so the
ring only shows on keyboard nav.

**Stackwise today.** Some elements have `focus:ring-2` (search input,
forms). Many do not (sidebar links, card buttons, sort dropdowns).

**Proposed adoption.** A global `*:focus-visible { outline: 2px solid
var(--accent); }` plus per-component `focus-visible:ring-2
ring-offset-1` where the outline doesn't visually fit.

## 18. Sub-second feedback for primary actions

**Convention.** Optimistic UI on every list mutation. The button
animates and updates state before the server response — the request
flies in the background; if it fails, the UI rolls back with a toast.

**Stackwise today.** Server-rendered with HTMX swap — typical latency
80-200ms, no optimistic update.

**Proposed adoption.** Two-step pattern using Alpine + HTMX:
1. Alpine sets `:class` for the active state immediately on click.
2. HTMX request fires; on success, server returns no-op (already
   updated visually). On failure, server returns a `HX-Trigger`
   `mediaUpdateFailed` event that Alpine listens for and rolls back.

## 19. Onboarding wizard

**Convention.** A short, optional wizard after signup. 2-3 steps:
"What do you track?", "Connect an existing tracker?", "Pick your
theme". Skippable. Stored on the user model.

**Stackwise today.** Signup → empty home. The user has to discover
sidebar, then discover import.

**Proposed adoption.** A `?onboarding=1` flow after signup that takes
the user through 3 steps. See `mocks/onboarding.html`.

## 20. Notifications inbox

**Convention.** A bell icon in the top bar opens a notification
center. Unread badge count. Items are typed (release / import / system).

**Stackwise today.** Notifications go out through Apprise to external
channels (Discord, Telegram). The in-app surface is a toast that
disappears.

**Proposed adoption.** Persist notifications in a `UserMessage` model
(`app/models.py` already has one). Bell icon in the top bar with
unread count. Click → dropdown with the last 10 items + "see all".

## 21. Keyboard shortcuts (beyond ⌘K)

**Convention.** Gmail-style "press `?` to see shortcuts". Useful set
for a tracker:

- `g h` jump to home
- `g d` jump to calendar (date)
- `g l` jump to lists
- `g s` jump to search
- `j` / `k` cycle through items in a list
- `w` mark watched on focused item
- `p` mark planning on focused item
- `e` edit (open track drawer)
- `?` show shortcut sheet

**Stackwise today.** Only `/` to focus search.

**Proposed adoption.** Implement a lightweight Alpine store that
listens for non-typing keypresses and dispatches actions. `?` opens a
shortcut sheet (`mocks/command-palette.html` shows the layout).

## 22. Density & touch targets

**Convention.** Minimum 36-44 px touch target on mobile; 28-32 px is
fine on desktop with hover affordances. Modern apps mix: hover-based
desktop dense, finger-based mobile spacious.

**Stackwise today.** Buttons are mostly `p-2` (32 px) or `px-4 py-2`
(36 px tall). Card overlay buttons are `p-2.5` rounded-full —
borderline at 32 px.

**Proposed adoption.** Codify in the design system: `button-sm` 28 px,
`button-md` 36 px, `button-lg` 44 px; primary actions on mobile use
`button-lg`.

## 23. Empty states with first-action CTAs

**Convention.** A good empty state shows: an illustration, a
one-sentence promise, two CTAs (primary action + secondary explanation).

**Stackwise today.** Empty states exist on most pages and they're
warm. Most just say "Browse Media". A few link to import.

**Proposed adoption.** Each empty state gets two concrete CTAs based
on the page:
- Home (no media): "Add your first movie" + "Import from a tracker"
- Calendar (no upcoming): "Add a TV show" + "Subscribe to ICS"
- Lists (no lists): "Create your first list" + "Browse templates"

## 24. Search-as-trigger

**Convention.** Notion's slash-command, Linear's `c` to create. Type
to act, not just to filter.

**Stackwise today.** Search submits to a results page.

**Proposed adoption.** The ⌘K palette covers this. The header search
input gains an inline-suggestions dropdown that lets the user
mark-watched without leaving the page.

## 25. Theme manager UX

**Convention.** GitHub's theme picker shows live preview swatches.
VS Code Themes shows full editor previews. iOS shows two preview
phones (light/dark).

**Stackwise today.** Theme is a `<select>` in the Preferences page.
Apply on next page load.

**Proposed adoption.** Move the picker to a popover in the top bar
(`mocks/_assets/tokens.css` includes the variable definitions for live
swap). Each theme renders as a 3-color swatch row. Apply applies
immediately via a JS class swap; persist on dropdown close.

## Anti-patterns to skip

A few patterns are popular but don't fit Stackwise's audience (self-
hosted, privacy-conscious, single-user-or-small-team):

- **Social timelines.** Letterboxd/AniList lean into follow / share /
  comment. Stackwise's multi-user model is "your household / your
  homelab", not "the public". Lists with collaborators is enough.
- **Recommendation engines.** "Because you watched X, try Y" requires
  off-server ML or third-party calls. Not worth the complexity.
- **Gamification.** Badges, levels, points — they fight the privacy /
  self-hosted ethos.
- **Push notifications.** PWA push is brittle and Apprise already
  covers the need.
- **Infinite-scroll-only collections.** Skip-to-page is critical for
  archive scrolling; pagination + load-on-revealed (Stackwise's current
  pattern) is the right hybrid.

## Inspiration sources

For reference — not direct quotes, but pattern echoes you'll see in
the mocks:

- **Letterboxd** for half-star ratings, detail-page composition, list
  density, year-recap narrative.
- **Trakt** for calendar shape, "up next" surface, scrobble lineage.
- **Plex / Jellyfin** for backdrop hero, continue-watching rail,
  poster grid.
- **AniList** for media-type-tinted accents, dense list view,
  customization options.
- **Linear** for the command palette, density toggle, keyboard nav.
- **Vercel dashboard** for the top bar shape, the right-aligned utility
  cluster.
- **Notion** for the settings shell (sidebar + content area), inline
  property editing.
- **StoryGraph** for stats-as-narrative, reading-goal pattern.
- **Backloggd** for "log entries" as activity surface, status pills.
