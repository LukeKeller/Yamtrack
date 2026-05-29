# Handoff — Book "Matched = provider" + every-book details page

**Date:** 2026-05-29
**Branch:** `claude/book-provider-match-details` (off `main` @ ff4d7dc3 / ynh151, the deployed commit)
**Phase 1 commit:** `116923f1` (committed, NOT pushed)

## Goal
Redefine an uploaded book's "Matched" to mean *resolved to a metadata provider (Hardcover/OpenLibrary)* instead of *linked to a book you track*, and give **every** uploaded book a details page even if untracked.

## Locked decisions
1. Auto-match on upload: Hardcover **first only if** the user has a connected `HardcoverIntegration` token, else/on-miss OpenLibrary (keyless). ISBN-13 first (convert ISBN-10→13), then conservative title+author. No match → mark NO_MATCH, never error.
2. Every book gets a details page: provider-matched → normal page; unresolvable → lightweight fallback page from the epub OPF metadata + its KOReader history. Page lives at **`/library/<id>/`** (library app).
3. "Matched/Unmatched" = provider-resolved; manual match picker becomes a **Hardcover/OpenLibrary search** (not the current tracked-books list). "Matched" stays a concept but is separate from "has a details page".

## DONE — Phase 1 (committed 116923f1, 43 library tests pass, makemigrations --check clean)
- `src/library/models.py`: `LibraryFile` gained `match_status` (UNRESOLVED/MATCHED/NO_MATCH), `match_method` (NONE/ISBN/TITLE_AUTHOR/MANUAL), `matched_at`, `is_matched` property. `item` FK kept (= provider link).
- Migrations `library/0002_libraryfile_match_method_and_more` (schema) + `0003_backfill_match_status` (data: item set→MATCHED/MANUAL, null→UNRESOLVED).
- `src/library/matching.py`: `resolve_library_file_to_provider(library_file)` — ISBN normalize, Hardcover-then-OpenLibrary, `Item.objects.get_or_create` provider Item, stamp fields. Never raises (logs + leaves UNRESOLVED on API error).
- `src/library/tasks.py`: `auto_match_library_file(library_file_id)` celery task.
- `src/library/views.py`: epub upload enqueues the task (new uploads start UNRESOLVED); `library_link` stamps MATCHED/MANUAL on link, UNRESOLVED on unlink.
- Tests: `src/library/tests/test_matching.py` (17) + updated `test_library.py`.

## DONE — Phase 2 (details page, commit 47cc29f)
- `library/views.py: library_detail` + `_library_reading_history`; url `library_detail` at `/reading/library/file/<id>/` (browser library lives under `/reading/` now, not `/library/`). Template `templates/library/detail.html`.
- Always renders from epub OPF metadata; finds KOReader history by the OPDS hash (`document_hash == koreader_filename_md5`) and, when matched, by `item`. When `match_status==MATCHED`, enriches via `services.get_media_metadata(...)` (falls back to local metadata on `ProviderAPIError`), shows the tracking state or a "Track this book" CTA into `media_details`.
- Linked from every library card + reading-inbox row.
- 7 tests in `test_library.py::LibraryDetailTests`.

## DONE — Phase 3 (inbox + picker rework, commit ce9dcd6)
- `library/matching.py: provider_search(user, query)` (Hardcover-if-token-else-OpenLibrary free-text search, normalised, never raises) + `bind_to_provider(...)` (manual match → same MATCHED state, `match_method=MANUAL`).
- `library/views.py: library_match_search` (HTMX results partial) + `library_match_apply` (`get_or_create` provider Item, stamp MATCHED/MANUAL, honour `next`). URLs `library_match_search` / `library_match_apply`.
- New components `templates/library/components/{provider_match_picker,match_search_results}.html`; the inbox rows, library cards, and detail page now search providers instead of selecting a tracked book. Detail page gained "Clear current match".
- Semantics realigned to `match_status` (not item-presence): `reading_index` count + `/reading/unmatched` inbox show `match_status != MATCHED`; `library_index` filters/counts + the card badge ("Matched / No provider match / Matching…") key on `match_status`.
- KOReader hash auto-bind stays tracked-book based by design (it binds onto the Item a file already resolved to). `find_matching_book` untouched.
- Tests in `test_library.py::{ProviderSearchTests,ProviderMatchViewTests,InboxProviderSemanticsTests}`.

## Status: ready to ship (P1–P3 landed together)
The half-migrated-UX concern from the original handoff is resolved — uploads provider-match AND the inbox/labels/picker all speak provider-match now. Not yet merged to `main` / bumped; that's the release flow below and needs user authorization.

## CI caveat (worth fixing separately)
`.github/workflows/app-tests.yml` runs `manage.py test app users integrations lists events` — it does **not** include `library` or `reading`, so none of this feature's tests run in CI. They pass locally (`DB_HOST= python manage.py test library reading --settings=config.test_settings`, 61 lib tests green). Adding the two apps to that line needs a workflow edit (CLAUDE.md says ask first / the PR check fails on `.github/**` changes).

## Cross-cutting (per Yamtrack/CLAUDE.md)
- Bump `serviceworker.js` VERSION if static/templates change. `makemigrations --check`. Django test runner with `config.test_settings` (celery eager), not pytest. `ruff`/`djlint`. History-aware bulk ops. Ship via the release flow (merge to main, bump ynh marker, pin yamtrack_ynh manifest) — needs user authorization. Run tests with `DB_HOST=` unset → SQLite (repo .env points at a non-local Postgres).

## Tooling caveat
This session's interactive terminal/Read output corrupted heavily (even local file reads); **subagents (Explore/general-purpose) were the reliable channel** — the Phase 1 work was done by a general-purpose subagent. A fresh session should reset this. Detailed plan also in personal memory `yamtrack-book-match-details-feature-plan.md`.
