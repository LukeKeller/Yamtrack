# 01 — Current state audit

Snapshot of the Yamtrack UI as of commit `874e45b` (dev / fork branch
`claude/ui-ux-audit-redesign-UFa0c`). Numbers in parentheses are file
paths inside `src/templates/` so findings stay anchored to code.

## TL;DR

Yamtrack already gets a lot right: it's responsive, theme-aware, fast
(HTMX live filtering, lazy-loaded images), supports nine media types
with the same data model, and has thoughtful empty states. It feels
like a self-hosted Trakt with broader scope.

What it's missing relative to 2026 media-tracker conventions:

1. **Visual hierarchy is flat.** Almost every surface uses one of two
   slate panel colors (`#2a2f35` / `#39404b`) and depth comes from
   palette steps rather than typography or composition. Detail pages
   have no hero/backdrop — a 250 px poster does all the visual work.
2. **Color is overused as decoration.** Five accent colors (indigo,
   emerald, amber, fuchsia, violet) compete on every detail page. Status
   has its own color system and media type has none, so "completed" can
   look identical to "in progress" depending on theme.
3. **Primary actions are crowded.** Detail pages and cards expose three
   equally-weighted colored buttons (track / lists / history). For most
   users only one (track) matters at a time.
4. **Tracking takes too many steps.** Adding a movie from search is 5+
   clicks because the track modal is a long full-screen form even when
   the user just wants to mark it "watched today".
5. **Theming is fragile.** `themes.css` overrides 19 hex tokens per
   theme by hand because the templates hard-code `bg-[#2a2f35]` instead
   of using semantic variables. Adding a new theme today means editing
   one CSS file with 19 overrides — and any new screen that introduces
   a new hex code breaks the existing themes silently.
6. **Power users have no shortcuts.** No command palette, no `g h` /
   `g l` jump-to bindings, no quick "+1 episode" shortcut. The only
   keybinding today is `/` to focus search.
7. **Mobile is responsive, not native.** The desktop layout shrinks
   correctly, but there's no bottom nav, no swipe gestures, no native
   share or status sheet — and modals (track / lists / history) are
   centered overlays rather than bottom sheets.
8. **The home page is a stack of grids.** It splits "In progress" /
   "Planning" by media type and shows up to N items per type. There's
   no "what's next", no continue-watching, no recent activity, no
   "today's releases" surface even though the data exists.

The redesign keeps the same stack (Django + HTMX + Alpine + Tailwind v4)
and the same data model. It changes layout, density, motion, palette
discipline, and the "primary action" calculus.

## Stack & global chrome

| Area | What it is | Source |
| --- | --- | --- |
| Layout | Fixed 256 px left sidebar (`lg:`), sticky 64 px top bar with global search; main column has `container mx-auto px-8 py-12` | `base.html:62-330` |
| Sidebar nav | Home, Browse, [enabled media types], Create Custom, Statistics, Music, Music Stats, Lists, Calendar — plus Settings + Logout in a footer block | `base.html:78-247` |
| Mobile chrome | Slide-in sidebar from left, hamburger in the top bar — no bottom nav | `base.html:64-74, 256-260` |
| Color base | Body `#212529`, sidebar `#1a1d20`, top bar `#1a1d20`, cards `#2a2f35`, inputs/buttons `#39404b`, hover `#454d5a` | `base.html:64-73`, `themes.css` |
| Accent | Tailwind `indigo-600` (#4f46e5) for primary, plus `emerald-600` lists, `amber-600` history, `fuchsia-600` sync, `red-700` destructive | media-card / details |
| Typography | Roboto Flex (variable, woff2), Tailwind's default sans stack fallback | `static/fonts/roboto-flex.woff2`, `main.css` |
| Themes | One CSS file (`themes.css`) overrides 19 hex tokens for Dracula, Catppuccin Mocha/Macchiato/Frappé, Nord, Gruvbox Dark, Tokyo Night via `html[data-theme="..."]` selectors with escaped-bracket attribute classes | `themes.css:14-206` |
| Icons | ~70 hand-curated SVGs in `templates/app/icons/`, included with `{% include %}` and a `classes` kwarg — no sprite, no icon component | `templates/app/icons/` |
| JS | HTMX 2.0.4, Alpine 3.14.9, jQuery 3.7.1 (only for Select2), Select2 4.1, lazysizes 5.3.2, Chart.js 4.4.9 (conditional), Chart.js Datalabels | `static/js/libraries/` |
| Forms | django-widget-tweaks for class injection, django-select2 for autocomplete (jQuery-bound) | `users/preferences.html`, `lists/components/list_form.html` |
| PWA | Service worker registered in `base.html`, manifest under `favicon/site.webmanifest` | `static/js/serviceworker.js` |

## Per-screen audit

### Sidebar (`base.html:73-247`)

**What it is.** Vertical nav with three groups: global (Home, Browse,
media types), tools (Create Custom, Statistics, Music, Music Stats,
Lists, Calendar), and footer (Settings, Logout). Active state is a
filled background and an indigo-tinted icon.

**Strengths.**
- Active link highlighting uses both background and icon color.
- Settings active state covers all seven settings sub-pages — the
  `if request.path == account_url or notifications_url or ...` chain in
  lines 225–232 is brittle but it works.
- Mobile slides in over a `bg-black/50` scrim — standard pattern.

**Issues.**
- **Three tools in the second group are music-shaped.** "Music" (record
  scrobbling history) and "Music Stats" are distinct from "Statistics"
  but they sit next to each other with no grouping label or divider.
  Most users won't track records and will see two music entries that
  do nothing for them.
- **No collapsed/icon-only mode.** A 256 px sidebar costs real estate
  on 1366×768 laptops, which still bracket the median display size.
- **Sidebar template repeats the same ~10-line link snippet eleven
  times.** Each block conditionally swaps a duplicate `{% include %}`
  on the icon for an active-state version. A `{% nav_item %}` tag would
  cut ~200 lines.
- **No badges.** "Calendar" should be able to show "3 today"; "Lists"
  should be able to show pending invitations. The data is there.
- **Logout is a `<button>` inside an inline form.** Fine, but visually
  it sits at the same weight as Settings — a destructive footer item
  should be visually demoted (or moved into a user-menu popover).

### Top bar / search (`base.html:251-322`)

**What it is.** Sticky bar with a centered search input, a media-type
dropdown stuck to its right edge, and a hamburger on mobile. `/` shortcut
focuses search (`static/js/searchShortcut.js`).

**Strengths.**
- The media-type segmented dropdown remembers the user's last search
  type (`user.last_search_type`).
- Submit-to-search-page form pattern works without JS.

**Issues.**
- **No quick-add from the input.** The search submits to a full results
  page. Modern trackers (Trakt, Letterboxd) show inline suggestions and
  let you mark watched from the dropdown without leaving the current
  page.
- **No command palette trigger.** ⌘K is the universal escape hatch in
  modern productivity apps (Linear, Notion, Vercel, GitHub) and the
  pattern fits Yamtrack perfectly: jump to media list, change theme,
  start an import, mark today's planned movie watched.
- **Right side of the top bar is empty.** No notifications, no theme
  toggle, no avatar — all three are conventional anchors that the
  redesign can occupy.
- **Mobile hamburger lives on the left of the search input** — pushing
  the search input off-center. A right-aligned avatar/menu fixes this
  and also frees up the gesture-affordance area for future "swipe to
  open sidebar".

### Home (`app/home.html`, `app/components/home_section.html`)

**What it is.** "Home" title + sort dropdown, then the calendar card,
then two sections (In Progress / Planning) — each section is a list of
media-type subgrids of cards. A `Load all (N)` button beneath each
subgrid swaps in the full list via HTMX.

**Strengths.**
- Cross-media-type homepage is the right call (most users track at
  least two).
- Sectioned by status, then by media type — readable.
- Calendar pinned to the top is helpful for "what's tonight".
- Empty section copy is warm ("Your planning shelf is still empty").

**Issues.**
- **No "Continue watching" / "Next up".** For TV/manga/games — the
  three media types where "what's the next episode/chapter/save" is the
  most-asked question — the user has to drill into the detail page.
  Yamtrack already has `formatted_progress` and `max_progress` per item;
  exposing "S03E05 → +1" on the card would be ~one HTMX endpoint.
- **No recent activity feed.** simple-history already tracks every
  state transition. A "you marked X completed yesterday" / "Y aired
  today" feed would close the data loop.
- **No "today / this week" cluster.** The calendar card lists
  upcoming releases generically; an additional "Today" pile + "This
  week" pile would surface immediately actionable items.
- **In Progress and Planning are the only two sections.** No Paused,
  no Recently completed. Users who park media in Paused (a real
  workflow for manga/games) lose visibility.
- **Sort dropdown applies to every section globally.** A user often
  wants "in progress by progressed_at desc" but "planning by added desc"
  — two different sorts. The current single-sort pattern is a
  compromise.
- **Section header colors hard-code accent.** The in-progress section
  is `indigo-400`, planning is `sky-400`; this is the only place sky-400
  is used. The pattern doesn't extend.

### Browse (`app/browse.html`)

**What it is.** Curated movie/TV discovery via TMDB categories ("Now
playing", "Popular", "Top rated", etc.) — two media-type tabs and a
list of category pills above a paginated grid.

**Strengths.**
- Server-rendered, paginated, fast — does its one job.
- Layout toggle (grid vs list) is consistent with media list.

**Issues.**
- **Discoverability.** It's the second sidebar item, with a flame icon,
  and most users will assume it's "what's new in Yamtrack". The label
  needs to communicate that it's TMDB-curated discovery for movies/TV.
- **TV / Movie only.** Anime/manga/games/books all have curatable
  feeds (MAL's seasonal, IGDB's upcoming, OpenLibrary's trending) but
  none surface here. Either commit to "Browse = movies/TV" by labelling
  it "Discover Movies & TV", or generalize.
- **Filter pills push to a new URL on each click.** Could be HTMX-swap
  for snappier feel.
- **No "added by other users on this server" community surface.** Even
  in a single-tenant homelab install, "what is my partner watching"
  is a real ask.

### Media list (`app/media_list.html`)

**What it is.** Per-media-type list page. Header is title + an
optional "Collection stats" panel (records-specific). Filter bar:
search input, status filter, sort dropdown, grid/table toggle. Body is
either a `media-grid` (2 col on mobile, auto-fill `minmax(180px,1fr)`
on `xs+`) or a table with columns Title / Score / Progress / Last
watched / Status / Start / End.

**Strengths.**
- HTMX-bound search input with 300 ms debounce — instant.
- Table layout for power users alongside grid for browsers.
- Empty state has a concrete "Browse {{ type }}" CTA.
- Records have their own stats panel (owned/wanted, decade, top
  artists/labels, top played 90d).

**Issues.**
- **Filter bar consumes 64 px vertical** for one search input + three
  dropdowns + a toggle. A consolidated `Filter & sort` button opening
  a popover (Linear / GitHub Projects pattern) would let the list
  start higher and feel less cluttered.
- **Status filter only.** No filter by score (≥ 8), no filter by tag,
  no filter by source. Real users have collections of 5k+ items.
- **No multi-select / bulk actions.** Marking 20 manga as completed is
  one-by-one today.
- **Grid uses `minmax(180px,1fr)` everywhere — same poster size for
  movies and games.** A user with 1000 entries benefits from compact
  density.
- **Table on mobile horizontally scrolls inside the card** with no
  visual indicator; columns are full width and labels read
  "Last Watched" / "Start Date" / "End Date" → for a 320 px viewport
  this is unreadable.
- **No "saved views".** A user who lives in `anime / in progress /
  score desc` should be able to bookmark that state.
- **The "Collection stats" panel is records-only** — clearly an
  experiment for the vinyl flow. A general pattern (stat strip per
  media type) would let TV, anime, etc. each have its own.

### Media details (`app/media_details.html`)

**What it is.** Two-column hero (poster + main details), then optional
sections: record listening stats, your history + actions + details (left
rail), cast / related / episodes (right column). Modals for track,
lists, history. The longest single template in the project at ~910
lines.

**Strengths.**
- Source/IMDb/RT/Metacritic ratings surfaced as small badge tiles
  (recent commit).
- "Key facts" strip (release, runtime, budget, etc.) below ratings.
- "Your notes" appears under synopsis when present, with read-more.
- "Repeats" fold-down lists every replay/reread with its own note +
  date.
- Suwayomi reader integration: manga get a "Read on Suwayomi" button.
- Records have a per-side spin logger and listening calendar — a
  genuinely novel UI for self-hosters with vinyl.

**Issues.**
- **No hero/backdrop image.** Movies and TV have backdrop art in TMDB
  (`backdrop_path`); games have IGDB screenshots; books have
  OpenLibrary cover_id. None are used. A 16:9 hero with gradient fade
  is now the convention everywhere from Letterboxd to Plex.
- **Five accent colors compete.** Genres are `violet-600` pills,
  primary CTA is `indigo-600`, Suwayomi is `emerald-600`, record spin
  buttons are `amber-600`, sync metadata is `fuchsia-600`, lists is
  `emerald-600`, history is `amber-600`, delete is `red-700`. A user's
  eye has nowhere to rest.
- **The primary "Add to tracker" button.** Looks the same when you
  have not yet added the media (`bg-gray-600`) as when adding it would
  be the primary intent — the gray weakens the call to action. After
  adding, it shows the status text — good — but the visual rhythm
  (button + edit pencil + chevron) overloads it.
- **Three "Actions" buttons grouped horizontally** (lists / history /
  sync) — same problem as the media card. Sync metadata is a power
  feature and shouldn't be a primary action.
- **Score display is a 120 px box that's clickable to open a 10-star
  popup row.** The popup is keyboard-inaccessible and the 10-button
  row layout doesn't communicate the half-star precision that the rest
  of the world uses.
- **Side details ("DETAILS" panel) shows everything not in the key
  facts strip,** unstyled — author, narrator, publisher, language,
  external links — and uppercases the field name. Inconsistent with
  the "key facts strip" pattern up top.
- **Episodes list is a flat vertical stack.** A 20-episode season is a
  20-card scroll. No "expand all by season", no compact rows, no
  per-episode chevron-to-expand. Each episode card has its own
  Track / Lists / History triplet of round colored buttons. Density is
  very low.
- **Repeats accordion** has a `Show Repeats (N)` button that toggles a
  list of more cards. Each card repeats most of the same fields.
  Better: show all repeats on a timeline.
- **Track / Lists / History triplet repeats four times per page** (top
  hero buttons, Actions row, on each episode, on each related card) —
  the visual language gets exhausted.
- **Modals overlap.** Track and Lists modals can both be open at once
  via Alpine state — clicking outside any one closes the topmost but
  the stack management is implicit. The repeats accordion's "edit"
  pencil opens *the same* track modal in a different mode.

### Search results (`app/search.html`)

**What it is.** Header with title + source pills (TMDB / MAL / IGDB
etc.) + grid/list toggle. Below: paginated grid or list of media cards.

**Strengths.**
- Source filter pills work for the multi-source media types.
- Pagination with ellipses and disabled prev/next buttons.

**Issues.**
- **No quick-add path.** Hover-overlay on cards exposes the Track
  modal which still requires the full form. For users importing
  hundreds of items from search, "mark all on this page as planned"
  would be a massive accelerator.
- **No saved searches / recent searches.**
- **No deep-link results from external places.** A "drag any URL into
  the search bar" (TMDB, MAL, Amazon, etc.) → resolve to media is a
  modern-tracker convention (Trakt does this).
- **Results don't show whether the user has already tracked this
  item.** A subtle "already in your TV list" pill on already-tracked
  cards prevents duplicate-tracking confusion.
- **No grid density toggle / no infinite scroll.** Pagination at the
  bottom of 20 results requires a click for every 20.

### Calendar (`events/calendar.html`, `events/components/calendar_card.html`)

**What it is.** Calendar card (used on both `/calendar` and the home
page). Header bar: prev/next month, "Today", "Fetch new releases", view
toggle (grid / list), download ICS link. Body: grid (month) or list
(agenda).

**Strengths.**
- The "Fetch new releases" button is a manual escape hatch when the
  periodic task hasn't run.
- ICS subscription URL is exposed verbatim — nice for self-hosters.

**Issues.**
- **Both views show the same density.** The grid view is dense and
  works on a desktop but collapses to vertical stack on mobile —
  swapping to list mode is a manual step. Auto-switching by viewport
  would help.
- **No filtering.** Show me only manga releases this month, hide
  rewatches, etc.
- **No today badge / count.** "3 releases today" pinned somewhere
  (sidebar Calendar item, top bar bell, etc.) would draw the eye.
- **ICS URL display.** The readonly text input with a copy-button
  fallback would beat the current "select-the-text-yourself" affordance
  (there's a `copy-item.js` for this elsewhere — reuse it).

### Lists (`lists/custom_lists.html`, `lists/list_detail.html`)

**What it is.** Lists overview grid (4 col on `lg`) showing cover, name,
description, collaborator avatars, item count. Detail page is a media
grid with filter/sort + collaborator chip.

**Strengths.**
- Collaborator avatar stack is a nice visual cue.
- The list-form modal is consistent with the rest of the modals.
- The list grid card uses an inset overlay over the cover image — looks
  good.

**Issues.**
- **List covers are a single image** (or a placeholder). 4-up cover
  mosaics from the first 4 items would communicate "this list has 12
  movies, here are 4 of them" at a glance.
- **No drag-and-drop reordering** of items within a list. Lists with a
  narrative order ("my top 10 of 2024") can't express it.
- **Public/private state isn't visualized on the list card** —
  collaborators are shown but you can't tell a public-link list from a
  collab-only list.
- **No list templates** ("Best of 2024", "To watch with my partner") to
  bootstrap creation.

### Statistics (`app/statistics.html`)

**What it is.** Date-range picker dropdown (predefined + custom range),
four big stat cards (Completed, Average rating, Most active day,
Current streak), an activity heatmap, four Chart.js panels (media
type distribution, status distribution, status stacked by type, score
stacked by type), top rated grid, vertical timeline of items by
month/year.

**Strengths.**
- The date range picker is the best component in the app — clean
  predefined-vs-custom tab, nice transitions.
- The heatmap is GitHub-contributions-style and instantly readable.
- The vertical timeline is a fresh take on "what did I consume this
  year" and works well at desktop sizes.

**Issues.**
- **Four equal-weighted cards** at top — Completed and Average rating
  are headline numbers, but "Most active day" and "Current streak"
  are tertiary stats. The four-card row visually equalizes them.
- **No "wrapped"-style summary.** Spotify Wrapped is now the canonical
  end-of-year stats experience. A `/statistics/2025-recap` view with
  scrolly-narrative panels would be a high-value, low-effort addition
  (the data and charts already exist; the format wraps them).
- **Activity heatmap doesn't drill in.** Clicking a cell should open
  "what did I do on Aug 14".
- **Timeline overflows horizontally on small viewports** with no scroll
  cue; the alternating-side layout flips to centered single column
  via media queries — fine, but visually busy.
- **Top rated section is just a media grid** — same density as the
  full media list. A "podium" presentation (1st bigger than 2nd, 2nd
  bigger than 3rd) for the top 3 would feel celebratory.

### Settings (`users/base.html`, sub-templates)

**What it is.** Left-rail sub-nav with 8 sections (Account,
Preferences, Notifications, Integrations, Import, Export, Advanced,
About). Each sub-page is a stack of cards with form sections.

**Strengths.**
- Sticky sub-nav with active state highlighting via a left indigo bar.
- Preferences page uses paired (label + toggle/select) rows — readable.
- Import page has a fixed-grid of sources with consistent card shape.

**Issues.**
- **Settings is one of 11 sidebar entries** in the global nav. With 8
  sub-pages it dwarfs every other top-level entry. Either:
  (a) Keep settings global but trim sub-pages (merge "Notifications"
      into "Preferences"?), or
  (b) Land settings on a hub page (the current `/account` lands on the
      Profile/Password page — the first sub-tab — instead of a chooser).
- **The sub-nav uses `border-l-2 border-indigo-500` for active.** This
  collides with the main app sidebar's "bg + icon color" active
  pattern. Two different active styles on adjacent UI elements.
- **Import page is dense.** 13 source cards in a 2-column grid. Each
  has its own conditional form + form fields. Grouping by category
  (movie/TV / anime/manga / books / games / music) would help.
- **No global search inside settings** for power users ("where's the
  toggle for episode obfuscation").
- **About page (not audited above) is just an info block.** Could be
  paired with version + update-availability status.
- **Periodic imports + import history live on the same page** — for
  users with active scheduled imports this is fine, but for users who
  only do CSV uploads the Active + History panels at the bottom are
  noise.

### Login / signup (`account/login.html`, `allauth/layouts/entrance.html`)

**What it is.** Centered card on a `#212529` background, `Yamtrack`
wordmark above. Form below the wordmark, social provider list below the
form, "Register now" link in a small line.

**Strengths.**
- Clean. Doesn't get in the way.
- Auto-submits the single SSO provider if `REDIRECT_LOGIN_TO_SSO` is
  on — nice.

**Issues.**
- **No marketing left rail.** Most self-hosted apps now run a two-pane
  entrance: marketing/feature pane on the left, form on the right. For
  Yamtrack this is a chance to show the demo URL, feature list,
  GitHub stars, etc., during the first impression.
- **No visual identity.** The "Yamtrack" wordmark is text-only and
  the brand is a teapot emoji. A small logomark + the wordmark would
  consolidate identity.
- **Social-account list looks like a list of stylelessly-rendered
  buttons.** A grid of equally-sized brand-color tiles would feel
  modern.

### Errors (404 / 500 / 400 / 403)

**What it is.** Centered card on `#212529`, big numeral, headline,
description, "Back to home" button.

**Strengths.**
- Consistent across the 4xx/5xx variants.
- Links to GitHub issues.

**Issues.**
- **No search input on 404.** "Did you mean to look for a movie?"
  pattern would convert lost users into searchers.
- **No randomly-suggested top-tracked media on 500.** Soft landing.

### Track modal (`app/components/fill_track.html`)

**What it is.** A `w-152` (`608 px`) centered modal with the full
status/score/progress/start/end/notes/repeats form. Submit creates or
updates; secondary button deletes (disabled if not yet tracked).

**Strengths.**
- Spinner-decorated number inputs for progress are a nice touch.
- Two-column auto-layout for forms with > 8 fields.
- Field labels are clear.

**Issues.**
- **It's a centered modal, not a drawer.** For "I just marked it
  watched today, now I want to set the score" the user wants the rest
  of the page still visible.
- **All fields are presented at once.** The 80% case is "mark watched
  today with no score or notes" → that should be one click. Power
  users get the full form via an "Edit details" reveal.
- **No quick-action buttons inside the modal.** E.g., "+1 progress",
  "Today as end date", "Repeat" — all hand-typed into number / date
  inputs today.
- **Delete and Submit are co-located** with no confirm step. A misclick
  on Delete removes the entry.

### Episode tracker (`app/components/fill_track_episode.html`)

(Not fully re-read — but the season detail page renders one per
episode.)

**Issues by inspection from `media_details.html:824-880`.**
- Each episode has a Track button that opens a per-episode track
  modal; another Lists button; another History button.
- For a 20-episode season, that's 60 modal instances generated
  server-side per page load. Lazy/HTMX-on-demand would be cheaper.
- No "mark all up to here as watched" shortcut, despite this being a
  one-click pattern in every other TV tracker.

## Cross-cutting friction

### Color discipline

Counted across the templates:

- **Status colors** (`{{ status|status_color }}` filter) — green for
  completed, blue/indigo for in_progress, sky for planning, amber for
  paused, red for dropped. Used as text/svg color, not as background.
  Consistent — good.
- **Section accent colors** — indigo for in_progress, sky for planning
  in `home_section.html`. Inconsistent with status colors above
  (status uses different greens / blues).
- **Action button colors** — indigo (track), emerald (lists), amber
  (history), fuchsia (sync), red (delete), violet (genres), yellow
  (stars), gray (disabled), gray-9/90 (overlay badges). Nine accents
  on a single page.
- **Theme-specific overrides** — themes.css remaps the slate panel
  colors but does *not* remap the accents. Dracula gets purple via
  `--color-purple-400` for its accent override on `#4f46e5` but
  everywhere else `bg-indigo-600` stays "Tailwind indigo-600" — the
  themes don't really feel different at the accent level.

### Hex tokens vs semantic variables

Counted by `grep -roh 'bg-\[#[0-9a-f]*\]' src/templates | sort -u`:

```
bg-[#1a1d20]   sidebar
bg-[#1e1e1e]   tooltip
bg-[#212529]   body
bg-[#23272b]   sidebar hover
bg-[#262a2f]   calendar export link panel
bg-[#272c31]   search input
bg-[#2a2e33]   media-type dropdown
bg-[#2a2f35]   primary card
bg-[#2c3136]   sidebar borders/active
bg-[#2f353e]   activity heatmap cell (lvl 0)
bg-[#313842]   settings sub-nav hover
bg-[#343a40]   sidebar active alt
bg-[#39404b]   input / secondary button
bg-[#3e454d]   image placeholder
bg-[#454d5a]   hover on secondary
bg-[#4a525d]   ...
bg-[#4b5563]   collab avatar
bg-[#4f46e5]   indigo accent (explicit, not via `indigo-600`)
```

Eighteen hex tokens. Most denote subtle elevation steps. Only 3 of
them ("card", "input", "hover") are conceptually distinct. The
redesign collapses these to 4 surface tokens (`surface-0..3`) and
defines them as CSS variables in `:root` and per-theme.

### Density

Across grids:

- `media-grid` (defined in `input.css`) — `grid-cols-2
  xs:grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4`
- Search/browse grid — `grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4`
- Episode list — `space-y-6` vertical stack
- Settings page — `p-6` per card, `mb-5` between rows
- Detail page — `gap-8 md:gap-10`, `mb-12`, `space-y-15` between home
  sections

There's a high baseline of padding. A density-conscious app should
collapse to `gap-3`/`p-3` for cards and `gap-2`/`p-2` for grid items.
Modern trackers (Plex, Trakt) feel almost too dense by comparison.

### Iconography

70+ SVGs, each `{% include %}`-d with a `classes` kwarg. The icons are
Lucide-shaped (stroke 2) but not Lucide-sourced — mixed weights,
inconsistent stroke widths in a few. The repo already vendors the SVG
files; switching to a single `{% icon %}` template tag that renders
from a JSON-ish dict would let the icons be themed and would shrink
template noise.

### Motion

Almost all animation is Tailwind/Alpine x-transition for modal/dropdown
fades. There's no:
- Page-level transition (HTMX boost would add this with a class).
- Skeleton or progressive load (most images use lazysizes + a gray
  placeholder).
- Press-feedback on buttons (no `active:scale-95` or ripple).
- Reduced-motion override.

### Accessibility

Spot checks:

- `cursor-pointer` is on every clickable thing — good intent, but many
  of these are `<a>` styled as buttons or `<button>`s that already
  get the cursor for free.
- `text-gray-500` on `#2a2f35` measures contrast ratio ~3.5:1 — fails
  AA for body text. Used heavily in metadata.
- Search input has no `aria-label`; the `<button>` icon has no label.
- Dropdowns use raw `<button>`s with no `aria-expanded` or `role`.
- Toggle switches in preferences use a styled checkbox — the visual is
  great, but no keyboard `focus-visible` style.
- All modals trap focus implicitly through Alpine but don't restore
  focus on close.
- Status icons in cards encode information through color only (red
  dropped vs green completed) with no text alternative.

### Performance / payload

- `htmx-2.0.4.min.js` (~45 KB), `alpinejs-3.14.9.min.js` (~40 KB),
  `jquery-3.7.1.min.js` (~88 KB), `select2-4.1.0.min.js` (~70 KB),
  `lazysizes-5.3.2.min.js` (~7 KB) loaded on every page. jQuery exists
  solely for Select2 — switching to Tom Select or Choices.js
  eliminates ~150 KB.
- Chart.js 4.4.9 is conditional (good).
- `mediaStatusDateHandler.js` + `searchShortcut.js` load globally
  (small, fine).
- No HTTP/2 push or critical-CSS extraction — relies on browser HTTP/2
  multiplexing.

### Mobile

- Sidebar slide-in works.
- Top bar collapses fine.
- `track-modal` is centered; on a 380 px iPhone viewport it gets
  `px-4` padding and shows the whole form vertically.
- Bottom-of-screen one-handed reach: there's nothing there. No bottom
  nav, no FAB, no quick-add.
- Episode list on TV detail page stacks image-then-content vertically
  — fine.
- Swipe gestures: none. Swipe-to-mark-watched on episodes would be a
  natural fit.

## What to keep

When the redesign lands, these are the patterns to preserve:

- HTMX live filtering and infinite-scroll-on-revealed.
- Alpine `x-data="{ open: false }"` dropdown pattern (it's well-baked
  into form handlers and screen readers cope).
- The track / list / history modal trio's separation of concerns.
- The "Repeats" fold-down — preserves real history without dominating
  the page.
- The "what verb to use for this media type" template tags
  (`media_past_verb`, `long_unit`) — they keep copy correct.
- The records spin logger + listening heatmap — the most successful
  bespoke micro-feature in the app.
- The custom hex palette's overall slate-on-near-black mood. The
  redesign tightens it but doesn't shift hue.
- Theme support is real and used — the redesign should preserve and
  improve it, not flatten back to one theme.
