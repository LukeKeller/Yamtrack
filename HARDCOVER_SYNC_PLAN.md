# Implementation Plan: Two-Way Hardcover ↔ Yamtrack Sync

## Goal

Add bidirectional sync between yamtrack's book library and a user's Hardcover.app account so that when a user adds, updates, or finishes a book in either system, the change appears in the other within minutes. The integration follows yamtrack's existing patterns (Trakt, AniList, Simkl) so it can be upstreamed as a PR.

## Operating principles

A few principles will guide every decision below; they're worth stating up front because they resolve a lot of micro-questions later.

**Last-write-wins by timestamp.** Every record on both sides has an "updated_at" equivalent (Hardcover: `updated_at`; yamtrack: `simple_history` `history_date` plus `progress_changed`). When the same book differs across sides, the newer timestamp wins. This is simple, predictable, debuggable, and right for personal sync. Anything fancier creates more bugs than it solves.

**Idempotent operations.** Every sync operation must be safe to re-run. We never assume the previous run completed. We always reconcile current state against current state, not "what changed since last time" — though we use `last_synced_at` as a hint to skip work, never as a source of truth.

**Hardcover IDs are authoritative for matching.** Yamtrack already supports `source='hardcover'` for books. We need a way to also tag OpenLibrary-sourced books with their Hardcover counterpart once matched, so we don't re-match on every sync.

**Never silently lose data.** A book that can't be matched should produce a visible warning, not a silent drop. A failed mutation should retry then surface to the user, not disappear into a log.

**Soft-coupled outbound, periodic inbound.** Outbound (yamtrack → Hardcover) uses Django signals for near-real-time push. Inbound (Hardcover → yamtrack) is periodic via Celery Beat because Hardcover doesn't offer webhooks. This is the same shape Trakt periodic-import already uses.

---

## Phase 0: Pre-work and de-risking

Before writing any production code, do these in order. Each one is cheap and catches a class of risk.

**0.1. Get a Hardcover API token and prove the round trip works.** Generate the token from your Hardcover settings page. Run the four queries you'll actually need — `me { id username }`, `me { user_books(...) { ... user_book_reads { ... } } }`, `insert_user_book`, `update_user_book` — against the live API with `curl` or the Hardcover GraphQL explorer. Verify the response shapes match what you'll code against. The `insert_user_book` response is wrapped: `{user_book: {id}, error}`, not just `{id}` — confirm this with your own eyes.

**0.2. Read three reference files in the yamtrack source.** Don't try to read the whole codebase. Read these specifically:
- `src/integrations/imports/trakt.py` — full template for the inbound sync pattern, including the OAuth-based version (PR #753) which is structurally identical to a token-based Hardcover client.
- `src/integrations/imports/anilist.py` — second reference for the same pattern, including its private-profile OAuth flow (PR #773).
- `src/app/providers/hardcover.py` — the existing read-only metadata provider. Your sync code will share the GraphQL endpoint and possibly some helpers with this file.

Take notes on: how OAuth/token state is stored, how the importer signals success/failure to the UI, how it interacts with `bulk_create_new_with_history`, how it handles the `mode` parameter (new-only vs. overwrite).

**0.3. Open issue #488 on the upstream repo.** Comment that you're working on Hardcover two-way sync and ask whether the maintainer would prefer (a) you build it as a self-contained integration like Trakt, or (b) you build a small REST API first that this and other integrations could consume. Their answer changes the project shape significantly. Don't wait forever for a response — give it a week, then proceed with option (a). Either way, opening the conversation early avoids redoing work.

**0.4. Decide on fork strategy.** This fork (`LukeKeller/Yamtrack`) integrates on `main` — feature work, bump markers, and the source pin all live there. Branch your work off `main` (e.g., `feature/hardcover-sync`) and keep `main` in sync with upstream by merging `upstream/dev` into it periodically (upstream develops on `dev`; this fork does not). When upstream releases, sync `main` and rebase your feature branch on `main`. Keep the feature branch in a state you could open as a PR at any moment.

**0.5. Stand up a local dev environment.** The README has the recipe — clone, install requirements-dev, set env vars, run `python manage.py migrate`, run server + Celery + Tailwind. Verify you can log in, add a book via Hardcover (the existing read-only provider), and that the book appears in your library. This validates your environment before you start changing code.

---

## Phase 1: Data model

Three new models and one set of edits to existing ones.

**1.1. `HardcoverIntegration` model** (in `src/integrations/models.py` — create the file if it doesn't exist; otherwise check where Trakt's OAuth token model lives and put it there).

Fields:
- `user` — `OneToOneField(User, on_delete=CASCADE, related_name='hardcover')`. One Hardcover account per yamtrack user.
- `api_token` — encrypted text. Use `django-cryptography` or a simple Fernet wrapper keyed off Django's `SECRET_KEY`. The token grants full account access — encrypted-at-rest matters.
- `hardcover_user_id` — integer, nullable. Cached after first connect so we don't query `me { id }` on every sync.
- `hardcover_username` — text, nullable. For display.
- `enabled` — boolean, default True. Lets the user pause sync without disconnecting.
- `sync_direction` — choice: `inbound`, `outbound`, `both`. Default `both`. Lets the user be conservative if they want.
- `sync_progress` — boolean, default True. Whether to sync reading-session progress, not just status changes.
- `sync_lists` — boolean, default False. Custom-list sync is more invasive; opt-in.
- `sync_reviews` — boolean, default False. Reviews are sometimes private; opt-in.
- `delete_on_remove` — boolean, default False. If True, removing a book from yamtrack also removes it from Hardcover. Off by default to prevent accidents.
- `last_inbound_sync_at` — datetime, nullable.
- `last_outbound_sync_at` — datetime, nullable.
- `last_full_sync_at` — datetime, nullable. Distinguishes "we did a delta poll" from "we did a reconcile-everything sweep".
- `last_error` — text, nullable. Latest error message for surfacing in UI.
- `last_error_at` — datetime, nullable.
- `created_at` / `updated_at` — auto.

**1.2. `HardcoverBookMapping` model** (same file).

Purpose: cache the resolved Hardcover book ID for each yamtrack `Item`, especially items whose `source` is `openlibrary` or `manual`.

Fields:
- `item` — `OneToOneField(Item, on_delete=CASCADE)`. Yamtrack `Item` row.
- `hardcover_book_id` — integer.
- `hardcover_edition_id` — integer, nullable. (Hardcover distinguishes books from editions; reading sessions are tied to editions.)
- `match_method` — choice: `direct_id`, `isbn`, `title_author`, `manual`. Useful for diagnostics.
- `confidence` — small integer 0–100, nullable. Heuristic match confidence; manual matches get 100.
- `last_verified_at` — datetime.

When the yamtrack `Item.source == 'hardcover'`, the `Item.media_id` IS the Hardcover book ID — no mapping row needed. The mapping table only stores cross-source matches.

**1.3. `HardcoverSyncLog` model** (same file).

Purpose: append-only log of sync events. Lets the user see "what did the last sync do?" and lets you debug.

Fields:
- `integration` — FK to `HardcoverIntegration`.
- `direction` — `inbound` or `outbound`.
- `event_type` — `book_added`, `book_updated`, `book_removed`, `reading_session_added`, `match_failed`, `error`, `rate_limited`, `sync_started`, `sync_finished`.
- `item` — nullable FK to `Item`.
- `hardcover_book_id` — nullable integer.
- `details` — JSON. Structured diagnostic info.
- `created_at` — auto.

Cap retention at 30 days via a Celery beat task; this table will grow.

**1.4. Edit to existing `Book` model** (`src/app/models.py`).

Add one field:
- `last_hardcover_sync_at` — datetime, nullable. Set to the timestamp of the last successful outbound push for this row. Used to detect "yamtrack changed, but the change came from a Hardcover inbound sync, so don't echo it back."

Why this matters: without it, an inbound sync writes to the `Book` row, which trips `post_save`, which fires the outbound signal, which pushes back to Hardcover, which… loops. The simplest cure is to compare `progress_changed` against `last_hardcover_sync_at` and skip outbound if they're within a few seconds of each other. (See Phase 4 for the full echo-suppression logic.)

**1.5. Migrations.** Standard `python manage.py makemigrations integrations` and `python manage.py migrate`. Yamtrack uses `simple_history` which auto-creates history tables; the new field on `Book` will get a corresponding history field automatically.

**1.6. Admin registration.** Register the three new models in `src/integrations/admin.py` (mask the API token in the admin display). Useful for self-debugging and matches yamtrack's pattern.

---

## Phase 2: Hardcover client library

Create `src/integrations/hardcover_client.py` — a thin wrapper around the GraphQL API. Don't pull in a heavy GraphQL client; `requests.post` to a single endpoint is enough.

**2.1. Class shape.**

```python
class HardcoverClient:
    BASE_URL = "https://api.hardcover.app/v1/graphql"

    def __init__(self, api_token: str): ...
    def _execute(self, query: str, variables: dict | None = None) -> dict: ...

    # Reads
    def get_me(self) -> dict: ...
    def list_user_books(self, since: datetime | None = None,
                        limit: int = 100) -> Iterator[dict]: ...
    def get_user_book(self, book_id: int) -> dict | None: ...
    def search_book(self, query: str) -> list[dict]: ...
    def find_book_by_isbn(self, isbn: str) -> dict | None: ...

    # Writes
    def insert_user_book(self, book_id: int, status_id: int,
                         **fields) -> int: ...  # returns user_book_id
    def update_user_book(self, user_book_id: int, **fields) -> None: ...
    def remove_user_book(self, user_book_id: int) -> None: ...
    def insert_user_book_read(self, user_book_id: int,
                              progress_pages: int, **fields) -> int: ...
```

**2.2. Rate limiting.** Hardcover's limit is 60 req/min per token. Use a token-bucket or simple sliding-window limiter inside the client. Persist the state in Redis (yamtrack already has Redis) so the limit holds across Celery workers, not just within one process. Key: `hardcover_rate:{user_id}`. On 429, back off exponentially: 5s, 15s, 60s, 300s, then surface the error.

**2.3. Error handling.** GraphQL doesn't use HTTP error codes for query-level errors — a 200 OK can contain `{"errors": [...]}`. Always check both `response.status_code` and `response.json().get("errors")`. Map known errors to typed exceptions: `HardcoverAuthError`, `HardcoverRateLimitError`, `HardcoverNotFoundError`, `HardcoverValidationError`, `HardcoverTransientError` (network/5xx), `HardcoverError` (catchall).

**2.4. Pagination for `list_user_books`.** Use `limit: 100` and `offset` paging. Order by `updated_at` ascending so we can resume on failure. Yield one user_book at a time to the caller — the calling code decides batch size for downstream work.

**2.5. Progress fetch strategy.** When `since` is provided, query only `user_books` where `updated_at: { _gt: $since }` so a poll on a 500-book library is one request, not 500. Yamtrack's existing pattern in `tmdb.py` and `mal.py` for caching responses in Redis is worth re-reading; you want the same idea for Hardcover metadata.

**2.6. Tests with VCR-style fixtures.** Use `responses` or `pytest-vcr` to record real Hardcover responses once and replay in CI. Yamtrack already has fixtures for TMDB/Trakt — match that pattern. Include fixtures for: empty library, 250-book library (pagination), rate-limited response, authentication failure, network error, validation error.

---

## Phase 3: Status and field mapping

Mapping is small but easy to get wrong. Make it a first-class module: `src/integrations/hardcover_mapping.py`.

> **Status (ynh92):** Phase 3.1 (status), 3.2 (score), 3.4 (dates) and the `dates_read_input` helper are now consolidated in `hardcover_mapping.py` as paired `*_to_yamtrack` / `*_to_hardcover` helpers. The inbound importer and outbound push task both route through them — nothing else hard-codes a Hardcover `status_id` or rating scale. `FieldMappingTests` in `tests/test_hardcover_push.py` covers round-trip stability. Phases 3.3 (progress), 3.5 (repeats), and 3.6 (notes/reviews) keep their existing handling.

**3.1. Status mapping.**

| Yamtrack status | Hardcover `status_id` |
|---|---|
| `Planning` | 1 (Want to Read) |
| `In progress` | 2 (Currently Reading) |
| `Completed` | 3 (Read) |
| `Paused` | 4 (Paused) |
| `Dropped` | 5 (Did Not Finish) |

This is bidirectional and complete — no ambiguity.

**3.2. Score/rating.** Yamtrack stores 0–10 decimal (one decimal place). Hardcover ratings are 0–5 with half-star resolution (0, 0.5, 1.0, ..., 5.0). Conversion: `hardcover_rating = yamtrack_score / 2`, rounded to nearest 0.5. Round consistently on both sides so `9.0 → 4.5 → 9.0` is stable. A score of 0 in yamtrack means "no rating" — map to null in Hardcover, not 0 stars.

**3.3. Progress.** Hardcover's `user_book_reads.progress_pages` is the equivalent of yamtrack's `Book.progress`. Both are integer page counts. One-to-one mapping. If a book has multiple reading sessions on Hardcover, take the most recent one's `progress_pages` for inbound; for outbound, append a new `user_book_read` rather than mutating the previous one (this preserves Hardcover's session history).

**3.4. Dates.** `start_date` ↔ `user_book_reads.started_at`; `end_date` ↔ `user_book_reads.finished_at`. Hardcover allows null for either — handle it.

**3.5. Repeats.** Yamtrack `Book.repeats` is "number of times completed". Hardcover models this as multiple `user_book_reads` rows on the same `user_book`. Inbound: `repeats = max(0, count(reads_with_finished_at) - 1)`. Outbound: when `repeats` increments, create a new `user_book_read` row.

**3.6. Notes/reviews.** Yamtrack `Book.notes` ↔ Hardcover `user_books.review_raw`. Only sync if `sync_reviews=True` on the integration. This is the field most users would consider "private" — opt-in is correct.

**3.7. The unmappable cases.** Some pieces don't map cleanly:
- Hardcover has tags/lists; yamtrack has lists. Different concept (yamtrack lists are user-defined collaborative collections; Hardcover lists are personal). Sync only when `sync_lists=True`, and only Hardcover→yamtrack as a one-way for v1.
- Hardcover has `privacy_setting_id` per book. Yamtrack has no analog. Ignore on inbound, default to user's Hardcover privacy default on outbound.
- Yamtrack `progress_changed` (MonitorField) has no Hardcover equivalent. This is fine — we use it locally for echo suppression.

Document every mapping decision in a docstring at the top of `hardcover_mapping.py`. Future-you and code reviewers will appreciate it.

---

## Phase 4: Book identity resolution

The single most error-prone part of this project. Get this right, or expect a long bug tail.

**4.1. The matching pipeline (yamtrack → Hardcover).** Given a yamtrack `Item`, find its Hardcover `book_id`:

1. If `Item.source == 'hardcover'`: `Item.media_id` IS the Hardcover book ID. Done.
2. Else, check `HardcoverBookMapping` for a cached match. Done if present and not stale (re-verify monthly).
3. Else, try to derive an ISBN. Yamtrack's metadata may include it (from OpenLibrary). Query Hardcover: `editions(where: {isbn_13: {_eq: $isbn}})` then walk to `book`. Confidence: 90.
4. Else, try title + first author + year. Hardcover's `search` endpoint with `query_type: Book`. Take the top result if its `users_read_count` is healthy and the year matches within ±1. Confidence: 60–70.
5. Else, mark unmatched. Log to `HardcoverSyncLog` with `event_type='match_failed'`. Surface in the UI via a "books that couldn't be matched" list.

Manually matched entries (user clicks "this is the right book" on an unmatched item) get `match_method='manual'`, confidence 100.

**4.2. The matching pipeline (Hardcover → yamtrack).** Given a Hardcover `user_book`, find or create the yamtrack `Item`:

1. Look for an `Item` with `(source='hardcover', media_id=str(hardcover_book_id), media_type='book')`. Done if present.
2. Look for a `HardcoverBookMapping` pointing to this Hardcover book ID. Use its `Item`.
3. If neither, create a new `Item` with `source='hardcover'`. Yamtrack already knows how to fetch metadata for Hardcover-sourced items via `app/providers/hardcover.py`. Use that path to populate title, image, etc.

Note the asymmetry: inbound sync may create new `Item` rows; outbound sync never does (a book has to exist in yamtrack before it can sync out).

**4.3. Echo suppression.** When inbound sync writes to a `Book` row, the `post_save` signal fires. Without protection, this triggers an outbound sync that re-pushes the same data to Hardcover. The cure:

- Inbound sync sets `Book.last_hardcover_sync_at = timezone.now()` in the same `save()` call as the data write.
- The outbound signal handler checks: if `(Book.progress_changed - Book.last_hardcover_sync_at) < 10 seconds`, skip outbound for this update.
- Use a thread-local flag (`_inbound_sync_in_progress`) as a belt-and-suspenders check during inbound sync runs — set it before writes, clear it after.

This is the trickiest correctness issue in the project. Test it explicitly: simulate an inbound sync, assert no outbound mutation fires.

**4.4. Conflict detection.** Before a write in either direction, fetch the current state of the other side and compare timestamps:
- If our timestamp is newer: write.
- If their timestamp is newer: skip our write, log to `HardcoverSyncLog` with `event_type='conflict_skipped'`, surface in UI.
- If timestamps are within 5 seconds: assume same edit, write anyway (idempotent).

This is naive last-write-wins. It works for personal sync. If you ever see real conflict bugs, revisit.

---

## Phase 5: Inbound sync (Hardcover → yamtrack)

Module: `src/integrations/imports/hardcover.py`. Mirror `trakt.py`'s structure exactly so reviewers can map function-to-function.

**5.1. Entry points.**
- `importer(user, mode='new')` — top-level, called by Celery task. Mode is `new` (only new/changed books since `last_inbound_sync_at`), `overwrite` (full re-sync), or `manual` (user clicked "Sync now").
- `import_books_for_user(integration, mode)` — does the work.

**5.2. The flow.**

1. Validate the integration: token present, `enabled=True`, `sync_direction in ('inbound', 'both')`.
2. Build the GraphQL query with appropriate `where` clause: `{updated_at: {_gt: $last_sync}}` for `new`, no filter for `overwrite`.
3. Stream results from `client.list_user_books()`. Process in batches of 50.
4. For each Hardcover `user_book`:
   - Resolve to yamtrack `Item` (Phase 4.2).
   - Map fields (Phase 3).
   - Check for existing `Book` row for this user+item.
   - If no `Book` row: create with `bulk_create_new_with_history` — yamtrack's existing helper that respects the `simple_history` audit trail. **This helper is the one that bit issue #337 with `bulk_create() prohibited` errors — read its docstring carefully and mimic Trakt's usage exactly.**
   - If `Book` row exists: compare timestamps (Phase 4.4). If we're updating, set `last_hardcover_sync_at` first, then save the row.
5. Log each operation to `HardcoverSyncLog`.
6. On success: update `integration.last_inbound_sync_at`, clear `last_error`.
7. On failure: set `last_error`, `last_error_at`. Don't update `last_inbound_sync_at` (so we retry the same window next time).

**5.3. Reading sessions.** When `sync_progress=True`, also fetch each `user_book_read` for in-progress and recently-finished books. Map the most recent session's `progress_pages` onto `Book.progress`, `started_at` onto `start_date`, `finished_at` onto `end_date`.

**5.4. Reading-history fidelity.** Hardcover's `user_book_reads` table is genuinely a list of reading sessions. Yamtrack's `simple_history` audit table is a list of every state change. These are conceptually similar but not identical. For v1, only sync the most recent session's progress. For v2, you could optionally backfill yamtrack history rows from past Hardcover sessions — but that's fork-territory work, probably not upstreamable, and not needed for "two-way sync" as commonly understood.

**5.5. Unmatched book report.** When matching fails, don't fail the whole sync. Log it, continue. At the end, the `HardcoverSyncLog` rows with `event_type='match_failed'` form a queue the user can review in the UI ("3 books on Hardcover couldn't be matched — click to resolve"). The UI gives them a search-and-pick interface to set a manual `HardcoverBookMapping`.

---

## Phase 6: Outbound sync (yamtrack → Hardcover)

Two layers: a real-time signal handler that enqueues work, and a Celery task that does the work.

**6.1. Signal handler** in `src/integrations/signals.py`:

```python
@receiver(post_save, sender=Book)
def queue_hardcover_outbound(sender, instance, created, **kwargs):
    integration = HardcoverIntegration.objects.filter(
        user=instance.user, enabled=True,
        sync_direction__in=('outbound', 'both')
    ).first()
    if not integration:
        return
    if _is_echo(instance):  # Phase 4.3
        return
    push_book_to_hardcover.apply_async(
        args=[integration.pk, instance.pk],
        countdown=10,  # debounce burst edits
    )

@receiver(post_delete, sender=Book)
def queue_hardcover_outbound_delete(...): ...
```

The 10-second `countdown` debounces rapid edits — if a user updates progress three times in 8 seconds, we only push once. Use Celery's `task_id` deduplication: `task_id=f"hc_outbound_{integration.pk}_{instance.pk}"` so a queued task replaces a pending one.

**6.2. Celery task** in `src/integrations/tasks.py`:

```python
@shared_task(bind=True, max_retries=5, autoretry_for=(HardcoverTransientError,
                                                       HardcoverRateLimitError),
             retry_backoff=True, retry_backoff_max=300)
def push_book_to_hardcover(self, integration_id, book_id):
    ...
```

The task:
1. Re-fetch the `Book` and `HardcoverIntegration` from DB (don't trust the queued state — it's stale).
2. Resolve the Hardcover `book_id` (Phase 4.1). If unmatchable, log and exit.
3. Check if a Hardcover `user_book` exists for this `(user, book)`. Cache the answer in `HardcoverBookMapping`.
4. Build the diff: which fields changed since `last_hardcover_sync_at`? Only push changed fields.
5. Issue the appropriate mutation:
   - No existing user_book: `insert_user_book` with status, score, dates.
   - Existing: `update_user_book` with the diff.
   - Progress changed and `sync_progress=True`: also `insert_user_book_read`.
6. On success: set `Book.last_hardcover_sync_at = timezone.now()` with **`Book.objects.filter(pk=book_id).update(last_hardcover_sync_at=now)`** (NOT `instance.save()` — that fires `post_save` again).

**6.3. Periodic outbound reconciliation.** The signal-driven path can miss updates: server was down when the change happened, signal handler crashed, Celery worker dropped the task. Add a periodic Celery Beat task `reconcile_hardcover_outbound` that runs every 6 hours, finds books where `progress_changed > last_hardcover_sync_at + 1 minute`, and re-queues them. This is the safety net; in normal operation it does nothing.

**6.4. Deletes.** If `delete_on_remove=True`, `post_delete` signal triggers `delete_book_from_hardcover` task that calls `delete_user_book` mutation. Default off — accidental deletes propagating to Hardcover would be a bad first impression.

---

## Phase 7: Periodic scheduling

**7.1. Celery Beat configuration.** Yamtrack uses `django-celery-beat` (DB-backed schedules). Add to the migrations a one-time `RunPython` that creates the periodic tasks:

- `import_hardcover_for_all_users` — every 1 hour. Iterates all enabled integrations, fans out to per-user `import_hardcover` subtasks.
- `reconcile_hardcover_outbound` — every 6 hours.
- `purge_old_hardcover_sync_logs` — daily, deletes log rows older than 30 days.
- `verify_hardcover_book_mappings` — weekly, re-verifies a fraction of mappings to catch Hardcover-side ID changes.

**7.2. Per-user task fan-out.** Don't iterate-and-call inside one task — that creates a task that runs for an hour. The orchestrator task should `.delay()` per-user subtasks and return immediately. Each subtask handles one user, has its own retry behavior, and respects per-user rate limits.

**7.3. Configurable schedule.** Power users will want to control sync frequency. Either:
- Add `inbound_sync_interval_minutes` to `HardcoverIntegration` (60 default), and use a custom scheduler that respects it.
- Or just expose a global env var `HARDCOVER_SYNC_INTERVAL_MINUTES` for v1 and add per-user later.

The second is simpler and matches yamtrack's existing approach.

---

## Phase 8: Connect/disconnect flow

Hardcover doesn't offer OAuth — it's a plain user-generated bearer token. This is actually simpler than Trakt's flow.

**8.1. Connect view.** A settings page at `/integrations/hardcover/`:

- Form with one field: API token (masked input).
- Help text with instructions and a link to `https://hardcover.app/account/api`.
- On submit:
  1. Construct a temporary `HardcoverClient` with the token.
  2. Call `client.get_me()`. If it fails: show the error inline, don't save.
  3. If success: save `HardcoverIntegration` with `hardcover_user_id`, `hardcover_username`, encrypted token.
  4. Show "Connected as @{username}" with options for sync direction, progress sync, lists, reviews, deletes.
  5. Offer a "Run initial sync now" button.

**8.2. Status page.** Same URL once connected. Shows:

- Connection status, username.
- Last inbound and outbound sync timestamps.
- Last error if any (with "clear" button).
- Sync direction toggle, sync_progress, sync_lists, sync_reviews, delete_on_remove checkboxes.
- "Sync now" button (queues both inbound and outbound).
- "Unmatched books" section if any exist, with manual-match UI.
- "Recent sync activity" — last 20 entries from `HardcoverSyncLog`.
- "Disconnect" button. On click, asks: "Disconnect Hardcover? Your local books and tracking data are kept. Synced books on Hardcover are also kept." On confirm: deletes the `HardcoverIntegration` row (cascades to mappings, logs).

**8.3. Implementation pattern.** HTMX templates, modeled on `templates/integrations/trakt.html`. Two views: `hardcover_settings` (GET, shows the page) and `hardcover_connect` / `hardcover_disconnect` (POST). One additional view `hardcover_sync_now` (POST) that queues a task.

**8.4. URL routing.** Add to `src/integrations/urls.py`:

```python
path('hardcover/', views.hardcover_settings, name='hardcover_settings'),
path('hardcover/connect/', views.hardcover_connect, name='hardcover_connect'),
path('hardcover/disconnect/', views.hardcover_disconnect, name='hardcover_disconnect'),
path('hardcover/sync/', views.hardcover_sync_now, name='hardcover_sync_now'),
path('hardcover/match/<int:item_id>/', views.hardcover_match, name='hardcover_match'),
```

Add a tile to the integrations index page.

**8.5. Token rotation.** Hardcover tokens auto-expire annually. When a sync gets `HardcoverAuthError`, mark the integration with `enabled=False` and `last_error="Token expired or invalid. Please reconnect."` Surface this prominently in the UI — a banner on the dashboard, not just a hidden settings page.

---

## Phase 9: Configuration and deployment

**9.1. Environment variables.** Add to settings.py:

- `HARDCOVER_API` — already exists for the metadata provider; reuse for fallback if a user hasn't set their own token (matches Trakt's pattern). But the user-token-based per-user sync should not depend on this. Document the distinction.
- `HARDCOVER_SYNC_INTERVAL_MINUTES` — default 60.
- `HARDCOVER_SYNC_ENABLED` — default `True`. Lets ops disable the integration globally without removing the code.

**9.2. Admin gate.** Like other integrations, the connect page should be gated behind a feature flag if `HARDCOVER_SYNC_ENABLED=False`.

**9.3. Documentation.** Two new wiki pages, modeled exactly on the Trakt and Simkl ones:
- `Hardcover-Integration.md` — user-facing setup guide.
- `Hardcover-Sync-Reference.md` — fields synced, conflict rules, troubleshooting.

Update `Environment-Variables.md` with the new vars.

---

## Phase 10: Testing

**10.1. Unit tests.** `src/integrations/tests/test_hardcover.py`. Coverage targets:
- Status/score/date mapping (every mapping case, both directions).
- ISBN extraction and normalization.
- Echo suppression: simulate inbound sync, assert no outbound task queued.
- Conflict resolution: stale local change yields skip-and-log.
- Rate limit handling: forced 429 → backoff → retry → success.
- Auth failure: token expired → integration disabled, error surfaced.
- Match failure: book with no ISBN, no Hardcover ID → logged, no crash.

**10.2. Integration tests with VCR.** Record real Hardcover responses for: empty library, 50-book library, library with active reading sessions, library with rereads. Replay in CI. Yamtrack's existing test infrastructure uses `responses` for HTTP mocking — follow that pattern.

**10.3. End-to-end test with Playwright.** Yamtrack uses `pytest-playwright`. Add one E2E test:
- Create a user.
- Visit `/integrations/hardcover/`.
- Submit a (fake) token. Mock the `me` query to succeed.
- Verify "Connected as testuser" appears.
- Click "Sync now". Mock the user_books query to return 3 books.
- Verify 3 books appear in the user's library.

**10.4. Migration test.** Yamtrack's migration tests are sparse but the data model addition warrants one: assert the `Book.last_hardcover_sync_at` field migrates cleanly on an existing populated database.

**10.5. Manual test plan** (run before submitting the PR):
1. Connect with a real Hardcover account.
2. Initial inbound sync — verify all books appear, statuses match.
3. Update a book in yamtrack — verify it appears in Hardcover within a minute.
4. Update the same book on Hardcover — verify it appears in yamtrack on next inbound sync.
5. Update on both sides within seconds — verify last-write-wins.
6. Add a book in yamtrack via OpenLibrary that ALSO exists on Hardcover — verify ISBN matching works.
7. Add a book in yamtrack with a fake ISBN — verify unmatched-books UI surfaces it.
8. Manually match the unmatched book — verify next sync works.
9. Disconnect, reconnect — verify state preserved.
10. Revoke the token on Hardcover side, trigger a sync — verify graceful auth-failure UX.

---

## Phase 11: Rollout

**11.1. Branch hygiene.** Keep `feature/hardcover-sync` rebased on `main` weekly (sync `main` from `upstream/dev` first). When a release happens upstream, sync, rebase, and re-test.

**11.2. Self-host first.** Run your fork in your own deployment for at least two weeks before opening the PR. Catch the bugs that only appear with a real library and time.

**11.3. Open the PR in pieces.** A 3,000-line PR scares maintainers. Split into:
- PR 1: Data models, migrations, admin (small, mechanical).
- PR 2: Hardcover client + mapping module (testable in isolation).
- PR 3: Inbound sync only (gives users value alone).
- PR 4: Outbound sync (the bigger conceptual leap).
- PR 5: UI polish, unmatched-books resolution, lists/reviews.

If the maintainer wants only some of these, you've structured the work so that's possible.

**11.4. PR description template.** Reference issue #488 and the existing Trakt integration. Include:
- Screenshots of the connect flow and status page.
- A short table of "what syncs / what doesn't" so reviewers can sanity-check scope.
- The mapping table from Phase 3 verbatim.
- A note about Hardcover's API being beta and the rate-limit/echo-suppression handling.

**11.5. Stay engaged after submitting.** Watch the Discussions tab and Discord; users testing the PR will hit edge cases. Respond fast. The dannyvfilms fork suggests this is part of the culture.

---

## Risk register

The risks worth holding in your head as you build, in rough order of likelihood:

**Echo loops** are the most likely correctness bug. The `last_hardcover_sync_at` mechanism plus the thread-local flag plus the timestamp window need to all agree. Test this explicitly and write a regression test.

**Hardcover API drift** is the most likely external bug. The booklore-app issue (#2297) shows real Hardcover schema changes have already broken integrations: `default_edition_id` was removed from the `books` type. Mitigations: introspect the schema on every connect and warn if expected fields are missing, query the minimum field set you need, log raw GraphQL errors for diagnostics.

**Book identity mismatches** will be the largest support burden. Plan for it: the unmatched-books UI is non-optional, not nice-to-have. A book that silently isn't syncing is the worst possible UX.

**`bulk_create_new_with_history` is a known sharp edge.** Issue #337 documents a real production bug. Read the helper carefully, mimic Trakt's usage, and add a test that exercises bulk-create with `simple_history` integration.

**Rate-limit exhaustion on first sync** for users with 500+ books. The first inbound sync needs ~5 GraphQL queries (paginated user_books). Outbound first-sync after a fresh Hardcover-empty account, though, would be one mutation per book. Throttle outbound bulk pushes to 50 req/min with a margin, and warn the user before kicking off a first outbound sweep.

**AGPL distribution.** If you ever publish a Docker image of your fork for others to use, you must publish source. For a private fork on your own server, no obligation. Worth a one-line mention in the README.

**Maintainer disagreement on direction.** The feature might land partially (e.g., inbound only), or not at all. The PR-in-pieces strategy minimizes wasted work. The dannyvfilms fork is proof that running your own divergent fork works long-term if needed.

---

## Effort estimate

For someone comfortable with Django and Celery, working part-time:

- Phase 0 (de-risk): half a day
- Phase 1 (models): half a day
- Phase 2 (client): one day
- Phase 3 (mapping): half a day
- Phase 4 (matching): one to two days — this is the genuinely hard part
- Phase 5 (inbound): one to two days
- Phase 6 (outbound): two days, including signal/echo work
- Phase 7 (scheduling): half a day
- Phase 8 (UI): one to two days, mostly templates
- Phase 9 (config + docs): half a day
- Phase 10 (tests): two days
- Phase 11 (rollout): ongoing

**Total: roughly two to three weeks of focused part-time work to a shippable v1**, plus a few weeks of self-hosted bake-in time before opening the PR.

The biggest unknowns are Phase 4 (matching) and Phase 6 (outbound + echo suppression). If those go cleanly, the rest is mechanical. If matching turns into a quagmire, the right move is to ship v1 with "Hardcover-sourced books only" and add cross-source matching in v2.

---

## What v1 explicitly does NOT include

Worth saying out loud so scope doesn't creep:

- Custom-list sync beyond toggle-it-on basic mode (one-way Hardcover→yamtrack).
- Backfilling yamtrack `simple_history` rows from Hardcover reading sessions.
- Multiple Hardcover accounts per yamtrack user.
- A diff/preview UI before sync ("here's what would change").
- Smart conflict resolution beyond last-write-wins.
- Mobile-specific UX.
- Webhook receivers (Hardcover doesn't offer them; this would be wishful).

Each of these is a perfectly reasonable v2 enhancement and a few are good follow-up PR candidates.
