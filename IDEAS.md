# Yamtrack fork — idea backlog

Working notes for the LukeKeller/Yamtrack fork. Not auto-generated; edit freely.
When something ships, move it to "Shipped" with the `~ynhNN` it landed in.

---

## Queue (approved, ship in this order)

These were the original short list (2026-05-23) and are the next things to build.

- [x] **Display all scores out of 10** — shipped ynh87 (2026-05-24).
- [x] **Stats / year-in-review page** — shipped ynh88 (2026-05-24). `/wrapped/` with year chips, hero stats, monthly bars, top rated, day-of-week callout. Reading depth (pages read + KOReader reading time) added ynh147 (2026-05-29); video/game runtime still deferred (needs runtime metadata we don't store).
- [x] **TMDB "Where to watch"** — shipped ynh89 (2026-05-24). Repositioned the existing provider lookup out of the bottom Details pile into the hero, made provider chips clickable via TMDB's region link, and labeled the region explicitly. Backbone (region preference, TMDB cache, filter_providers) was already in place.
- [ ] **Bulk-select on lists** — multi-select checkboxes → bulk status/score/delete/add-to-list. Alpine store + action bar on `media_grid_items.html` / `media_table_items.html`; new `bulk_action` view that routes through `Media.save()` for safety, raw `update()` only for pure score/status changes.
- [x] **PWA install + offline list browse** — shipped ynh112 (offline page, runtime caching, install prompt, web push, background-sync write queue).
- [ ] **Smarter duplicate/merge detection** — when adding from `mal`, check if same canonical work is already tracked via `openlibrary`/`hardcover`/`tmdb` (fuzzy title+year), offer merge. Heavier follow-up: management command that ranks suspected duplicates across the library.
- [ ] **Hardcover inbound sync** — push side already shipped (ynh82). Plan in `HARDCOVER_SYNC_PLAN.md`. Still TODO: `me { user_books }` poll, identity map (`HardcoverBookMapping`), echo suppression via `last_hardcover_sync_at`.
- [x] **List Import (paste-and-match)** — shipped ynh111 as `/list/import`. Picks one media type, searches each pasted title, takes the top hit, batch-adds to a new CustomList. The per-row "pick from candidates" review for ambiguous matches is a future polish.
- [x] **KOReader visibility A+B** — shipped. Per-book reading history is inlined on the book detail page (ynh143) and the Reading hub at `/reading/` carries the devices/sync workspace (ynh141). Backed by `KOReaderProgressEvent` (an append-only event log added alongside the original mapping).
- [x] **KOReader visibility D** — shipped. Reading-cadence stats (`compute_daily_cadence`, contribution-grid heatmap) live on the Reading hub / cadence view.
- [x] **KOReader visibility F** — shipped. Inferred reading sessions (`compute_sessions`, 30-min idle gap) render on the book page and hub. Single-sync sessions were being dropped; fixed ynh146.

---

## Brainstorm pool (2026-05-24 deep dive — not yet approved)

User picks from this list once the queue above is shipping. Grouped by theme. None of these are commitments.

### Re-engagement & discovery
- **Annual reading/watching goal ring** — new `User` fields for pages/hours/completed targets, ring on home + stats.
- **"Did you finish?" nudge** — items in `In progress` with `progressed_at` stale by N days (book 30d / TV 21d / game 60d), with one-click Paused/Dropped/Completed. Mirrors `_stale_planning`.
- **New-episode alerts on Up Next** — badge cards where `next_event.datetime` ≤ now AND `progress` < released-episode count. `_annotate_tv_released_episodes` already exists.
- **"Because you finished X" recommendations rail** — extend `_comparable_items` with TMDB `/recommendations` seeded by recent completions, cache 24h.
- **Custom mood tags** — let users save curated moods (comfort, gym, with-kids) as a per-user M2M on `Item`, surface alongside `MOOD_LABELS`.

### Stats depth
- **Rating-quirks dashboard** — mean/median/stddev per media type, harshness index vs. global TMDB/MAL means, time-to-rate distribution. All from existing `score` + `simple_history`.
- **Per-decade / per-genre heatmaps** — backfill `Item.genres` JSON on first metadata fetch. Generalize `_build_by_decade` from records. Unlocks "top 5 directors/authors/studios."
- **Watch-time leaderboard** — daily/weekly/monthly hours watched. Derivable from existing `Item.runtime` + `Episode` count.

### Power user & API
- **Public read-only API (DRF or Ninja)** — token-auth like `quick_log`. List/search/details endpoints. Unlocks third-party widgets, Home Assistant cards.
- **Bulk-edit via CSV round-trip** — mirror `exports.py`; import edits keyed on `source`+`media_id`.
- **Desktop bookmarklet** — `bookmarklet.js` that POSTs current URL to `/share-intake/` with the user's token. Brings PWA share parity to desktop.

### Integrations
- ~~**TMDB "Where to watch"**~~ — promoted into the Queue 2026-05-24.
- **OpenLibrary "next in series" link** — surface series-next book on detail page with "Add to planning."
- **OPDS feed (read-only catalog of tracked books)** — `/opds/books.xml` listing user's Planning books with OL cover + upstream download links. Native Koreader/Moon+ Reader subscribe. No server-side file storage — links point at OpenLibrary / Standard Ebooks / Project Gutenberg / etc. when available.
- **OPDS *server* with uploaded epubs** — separate from the feed above: a real file host. Upload epub/cbz/pdf via Yamtrack (UI + maybe `/api/library/upload` for scripted bulk-imports), store under `MEDIA_ROOT/library/<user_id>/<sha256>.epub`, generate metadata from epub OPF (title, author, language, cover) and reconcile against tracked `Book` entries by ISBN / title-author match. Serve `/opds/library.xml` (browseable catalog) + `/opds/library/<work_id>` (acquisition feed with the download link) so KOReader's "Add OPDS catalog" flow points at one URL and the e-reader can browse + pull files. Auth via the existing API token (Basic / x-auth headers). Storage budget needs thought — epubs are small (~1 MB) but PDFs aren't; add per-user quota + admin storage-cap setting. Plays well with `Book.progress` / KOReader sync: download from Yamtrack → read with KOReader → KOReader pushes progress back via existing kosync.
- **KOReader sync data visibility** — today's UI only surfaces the integrations page's "recent syncs" list. Build a richer view: per-book reading timeline (percentage vs. time, derived from `simple_history` on `Book` + `KOReaderBookMapping` updates), per-device summary (which device synced what / last seen / page-count), reading-cadence stats (pages or percent/day) reusing the `_recent_activity` pattern. Also worth: a "stuck books" rail using progress + stale `progressed_at` (mirrors the queue's "Did you finish?" nudge, but specific to KOReader-synced books which tend to creep). All derivable from existing data — no new model fields, just views and templatetags.
- **Letterboxd CSV import + export** — already have GoodReads-style CSVs; mirror Letterboxd format both ways.

### Lists & social
- **Public list pages** — add `is_public` + slug to `CustomList`, render at `/lists/<slug>/<owner>` without auth. Shareable "Top 10 X" links.
- **List embed widget** — `?embed=1` renders sandboxed iframe-friendly grid (no nav/chrome).
- **Friends / following (MVP social)** — `Follow` model, new home rail "Friends' recent activity" reusing `_recent_activity`. Opt-in profile visibility.

### Data hygiene & operations
- **Search-result "Already tracking" badge** — annotate `cmdk_search` + `media_search` TMDB rows with the user's tracking status.
- **Inbox / triage queue** — unify unmatched scrobbles + share-intake URLs + new-on-shared-list items into one `/inbox`. Generalize the unmatched scrobble resolver.
- **Per-episode notes** — `Episode.notes` free-text field, render below episode row. Rides on `simple_history`.
- **Soft-delete + 30-day undo** — `Media.deleted_at`, `/trash` view, nightly purge.
- **Health page / observability** — `/admin/health`: Redis up, Celery beat heartbeat, last successful task per beat schedule, provider success rates.

### Mobile / UX polish
- **Swipe gestures on cards** — swipe-right +1 progress, swipe-left → status sheet. Alpine + touch events.
- **Watch-with mode** — separate progress per "watch partner" (spouse, kids). New `WatchSession` table.
- **Home composer** — toggle which home sections show. Home already has 7+ rails; turning some off becomes important as more land.

---

## Shipped (recent — see git log for the full list)

- ynh150 — **Reading pace + projected finish on the book page** (in-progress books with a multi-day KOReader window get a pace estimate — pages/day — and an extrapolated finish date callout in the reading-history section)
- ynh149 — **Games list playtime stats panel** (collapsible Playtime Stats on `/medialist/game`: total hours, completed, average over played games, top-games-by-playtime bar list; games store progress as minutes)
- ynh148 — **Up Next unwatched-episode count badge** (Plex-style cover badge = released minus watched for episodic types; hidden when caught up so it reads as a "new episode is out" nudge)
- ynh147 — **Reading depth in year-in-review** (pages read from completed books + KOReader reading time, folded into `/wrapped/`) ✓ from queue
- ynh146 — **Fix: single-sync KOReader reading sessions no longer vanish** (a session pushed as one event that advanced progress was dropped as a book-open ping; kept now when it shows forward progress)
- ynh141/143 — **Reading hub + inline KOReader history** ✓ from queue (visibility A+B/D/F)
- ynh112 — **PWA upgrade** (offline, install, web push, background sync) ✓ from queue
- ynh111 — **List Import (paste-and-match)** (new `/list/import` page: name + media type + textarea of titles → searches each, takes top hit, batch-adds to a new CustomList. Empty-match runs clean up the empty list; partial-match runs surface unmatched titles via messages. Cap at 100 titles per import.)
- ynh110 — **Release Date sort on custom lists** (`Item.air_date` generalized from "episode air date" to a premiere/release date for any media type; new `ListDetailSortChoices.RELEASE_DATE`; `lists_modal` populates `air_date` at Item-creation time; `backfill_item_release_dates` management command for existing rows)
- ynh89 — **Where to watch polish** (TMDB streaming chips moved into the detail-page hero, clickable to the JustWatch region link, region labeled in the heading) ✓ from queue
- ynh88 — **Year in review page at /wrapped/** ✓ from queue
- ynh87 — **Display all scores out of 10** (detail page hero now matches the IMDb/Hardcover pill style; cards/list/stats already were /10) ✓ from queue
- ynh86 — Show fork build version in settings sidebar
- ynh85 — Themes + font picker, live preview
- ynh84 — Mobile track drawer blank fix
- ynh83 — Book drawer comment fix
- ynh82 — **Hardcover sync: push book progress to Hardcover on save** ✓ from queue
- ynh81 — **Quick-rate from cards: kebab popover + 1-9/0 hotkeys** ✓ from queue
- ynh80 — Auto-mark prior episodes preference
- *(see `src/app/release_notes.py` for full history)*

---

## Rejected

- Plex/Jellyfin scrobble webhook (user not interested 2026-05-23).
