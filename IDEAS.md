# Yamtrack fork — idea backlog

Working notes for the LukeKeller/Yamtrack fork. Not auto-generated; edit freely.
When something ships, move it to "Shipped" with the `~ynhNN` it landed in.

---

## Queue (approved, ship in this order)

These were the original short list (2026-05-23) and are the next things to build.

- [ ] **Display all scores out of 10** — detail page hero still shows stars. Cards/table/stats already use `formatted_score` (/10). Quick-rate UI is already 1-10. *(in progress 2026-05-24)*
- [ ] **Stats / year-in-review page** — yearly hours, genre mix, completion streaks. Reuses `app/statistics.py` aggregates (`calculate_streaks`, `get_timeline`, `get_activity_data`, `get_music_stats`). Genre rollup needs `Item.genres` denormalization or live API w/ cache.
- [ ] **Bulk-select on lists** — multi-select checkboxes → bulk status/score/delete/add-to-list. Alpine store + action bar on `media_grid_items.html` / `media_table_items.html`; new `bulk_action` view that routes through `Media.save()` for safety, raw `update()` only for pure score/status changes.
- [ ] **PWA install + offline list browse** — SW already exists (`app/serviceworker.js`); cache home shell + last-rendered list HTML on background sync. Image cache via Cache API with LRU.
- [ ] **Smarter duplicate/merge detection** — when adding from `mal`, check if same canonical work is already tracked via `openlibrary`/`hardcover`/`tmdb` (fuzzy title+year), offer merge. Heavier follow-up: management command that ranks suspected duplicates across the library.
- [ ] **Hardcover inbound sync** — push side already shipped (ynh82). Plan in `HARDCOVER_SYNC_PLAN.md`. Still TODO: `me { user_books }` poll, identity map (`HardcoverBookMapping`), echo suppression via `last_hardcover_sync_at`.

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
- **TMDB "Where to watch"** — `/movie/{id}/watch/providers`, cache 12h, per-user country, render flag-aware streaming chips on detail pages.
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
