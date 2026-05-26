# Yamtrack fork — idea backlog

Working notes for the LukeKeller/Yamtrack fork. Not auto-generated; edit freely.
When something ships, move it to "Shipped" with the `~ynhNN` it landed in.

---

## Queue (approved, ship in this order)

These were the original short list (2026-05-23) and are the next things to build.

- [x] **Display all scores out of 10** — shipped ynh87 (2026-05-24).
- [x] **Stats / year-in-review page** — shipped ynh88 (2026-05-24). `/wrapped/` with year chips, hero stats, monthly bars, top rated, day-of-week callout. Hours-watched / pages-read deferred (needs Item runtime/pages backfill).
- [x] **TMDB "Where to watch"** — shipped ynh89 (2026-05-24). Repositioned the existing provider lookup out of the bottom Details pile into the hero, made provider chips clickable via TMDB's region link, and labeled the region explicitly. Backbone (region preference, TMDB cache, filter_providers) was already in place.
- [ ] **Bulk-select on lists** — multi-select checkboxes → bulk status/score/delete/add-to-list. Alpine store + action bar on `media_grid_items.html` / `media_table_items.html`; new `bulk_action` view that routes through `Media.save()` for safety, raw `update()` only for pure score/status changes.
- [ ] **PWA install + offline list browse** — SW already exists (`app/serviceworker.js`); cache home shell + last-rendered list HTML on background sync. Image cache via Cache API with LRU.
- [ ] **Smarter duplicate/merge detection** — when adding from `mal`, check if same canonical work is already tracked via `openlibrary`/`hardcover`/`tmdb` (fuzzy title+year), offer merge. Heavier follow-up: management command that ranks suspected duplicates across the library.
- [ ] **Hardcover inbound sync** — push side already shipped (ynh82). Plan in `HARDCOVER_SYNC_PLAN.md`. Still TODO: `me { user_books }` poll, identity map (`HardcoverBookMapping`), echo suppression via `last_hardcover_sync_at`.
- [x] **List Import (paste-and-match)** — shipped ynh111 as `/list/import`. Picks one media type, searches each pasted title, takes the top hit, batch-adds to a new CustomList. The per-row "pick from candidates" review for ambiguous matches is a future polish.

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
- **OPDS feed** — `/opds/books.xml` listing user's Planning books with OL cover + download links. Native Koreader/Moon+ Reader subscribe.
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
