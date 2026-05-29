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

## TODO — Phase 2 (details page)
- New view + url `/library/<id>/` + template. Always render from epub OPF metadata (title/author/cover) + KOReader history (look up `KOReaderBookMapping`/events by user+item if matched). When `match_status==MATCHED`, enrich from provider (`services.get_media_metadata(item.media_type, item.media_id, item.source)`), show "track this" CTA (reuse the existing media_save/track flow). Link every library row + reading inbox row to this page.
- `media_details` (src/app/views.py ~1112) already renders untracked from provider metadata — reuse patterns; the new page is the home for uploaded books incl. unresolved ones.

## TODO — Phase 3 (inbox + picker rework)
- `src/reading/views.py reading_unmatched` + `src/reading/helpers.py ranked_book_choices`: replace the tracked-books picker with a provider SEARCH (Hardcover/OpenLibrary) for library files; the match action should `get_or_create` a provider Item and set MATCHED/MANUAL. Relabel "Matched/Unmatched" (provider-resolved). Update `reading_index` `library_unmatched` count to `match_status != MATCHED` (inbox shows UNRESOLVED + NO_MATCH).
- Fix `library/index.html` "Tracked:" badge → "Matched (provider)" semantics.
- Decide whether KOReader auto-bind (`integrations/koreader.py`, still uses `find_matching_book`) should also move to provider matching or stay tracked-book based.

## Deployability note
Phase 1 alone is migration-safe and won't crash, but it ships a half-migrated UX (upload now provider-matches while inbox/labels/picker still assume tracked-book). Prefer shipping 1→3 together. A tiny back-compat shim could make P1 standalone-safe if needed.

## Cross-cutting (per Yamtrack/CLAUDE.md)
- Bump `serviceworker.js` VERSION if static/templates change. `makemigrations --check`. Django test runner with `config.test_settings` (celery eager), not pytest. `ruff`/`djlint`. History-aware bulk ops. Ship via the release flow (merge to main, bump ynh marker, pin yamtrack_ynh manifest) — needs user authorization. Run tests with `DB_HOST=` unset → SQLite (repo .env points at a non-local Postgres).

## Tooling caveat
This session's interactive terminal/Read output corrupted heavily (even local file reads); **subagents (Explore/general-purpose) were the reliable channel** — the Phase 1 work was done by a general-purpose subagent. A fresh session should reset this. Detailed plan also in personal memory `yamtrack-book-match-details-feature-plan.md`.
