# CLAUDE.md

Guidance for AI assistants (Claude Code, etc.) working in this repository. Read this file before making changes — Stackwise has a few load-bearing conventions (history-aware bulk ops, Item/Media split, MonitorField echo-suppression hooks) that aren't obvious from a casual scan.

## What Stackwise is

A self-hosted, multi-user Django app for tracking media: movies, TV (with seasons/episodes), anime, manga, games, books, comics, and board games. It pulls metadata from external providers (TMDB, MAL, IGDB, OpenLibrary, Hardcover, ComicVine, BoardGameGeek, etc.), supports webhooks from Jellyfin/Plex/Emby, and imports/exports from Trakt, Simkl, AniList, MyAnimeList, Kitsu, GoodReads, HowLongToBeat, IMDB, Steam, and CSV.

This is a **single self-contained repo** (`LukeKeller/stackwise_ynh`): it holds both the Django app (`src/`) and its YunoHost package (`manifest.toml`, `scripts/`, `conf/`, `doc/` at the repo root). There is no separate packaging repo, no orphan branch, and no upstream fork to sync. Stackwise started as a fork of [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) (FuzzyGrim) and is a derivative work under **AGPL-3.0** — preserve upstream attribution and the license notice (relevant if you redistribute a modified Docker image).

## Naming convention (READ THIS before renaming anything)

- **User-facing identity is "Stackwise"** — UI brand, PWA name, the YunoHost app (`id = stackwise`, path `/stackwise`, services `stackwise` / `stackwise-celery` / `stackwise-celery-beat`), service descriptions.
- **Internal identifiers stay `yamtrack`** — the Django app, `Celery("yamtrack")`, Python module paths, DB tables, service-worker cache keys (`yamtrack-shell-*`), the `yamtrackAppearance` localStorage keys, and `YAMTRACK_PYTHON_*` / `yamtrack_*` helpers in `scripts/`. Renaming these is user-invisible and would force DB migrations, reset saved prefs, or orphan Celery tasks. **Do not rename them.**
- The **"Import from Yamtrack"** feature (and its `source_display "yamtrack"` id) stays "Yamtrack" — it imports the upstream app's CSV format.
- Rule of thumb: if a user or the server operator sees it, it's "Stackwise"; if only the code sees it, it stays `yamtrack`.

## Tech stack

- **Python 3.12**, **Django 5.2** (`django.contrib.auth.middleware.LoginRequiredMiddleware` is on by default)
- **SQLite** (default, with WAL pragmas in `app/signals.py`) or **PostgreSQL** (set `DB_HOST` env var)
- **Redis** for cache + Celery broker (the `requests-ratelimiter` provider buckets are in Redis too)
- **Celery + django-celery-beat** (DB scheduler) + **django-celery-results** (DB result backend)
- **django-allauth** (account + 100+ social providers, OIDC)
- **django-simple-history** (audit trail on every `Media` subclass — see `bulk_create_with_history` rule below)
- **django-model-utils** (`FieldTracker`, `MonitorField` for `progressed_at`)
- **Tailwind CSS v4** (`static/css/input.css` → `static/css/main.css`, compiled output is committed and served by collectstatic; rebuilt by `./build-css.sh` and by the `tailwind-build` pre-commit hook whenever `input.css`, `themes.css`, any template, or class-emitting Python changes. **Neither the Dockerfile nor the YunoHost installer re-runs Tailwind** — if `main.css` falls out of sync with `input.css` the deployed instance loads CSS that doesn't define your new utility classes, which is harder to diagnose than it sounds. Let the hook run, or run `./build-css.sh` manually before pushing.)
- **HTMX + django-widget-tweaks + django-select2** for interactive UI without a JS framework
- **pytest-django** + **pytest-playwright** (Playwright is installed in CI)
- **ruff** (lint + format) and **djlint** (HTML lint) wired into pre-commit

## Repository layout

```
src/
├── manage.py
├── config/                  # Django project (settings, URLs, Celery, gunicorn)
│   ├── settings.py          # all env-var wiring; secrets via decouple + /run/secrets/<NAME>_FILE fallbacks
│   ├── test_settings.py     # CELERY_TASK_ALWAYS_EAGER=True, fakeredis cache
│   ├── celery.py            # `app = Celery("yamtrack")`; autodiscover_tasks across all installed apps
│   └── urls.py
├── app/                     # Core media tracking app
│   ├── models.py            # Item, Media (abstract), TV/Season/Episode/Movie/Anime/Manga/Game/Book/Comic/BoardGame, Sources, MediaTypes, Status, UserMessage
│   ├── providers/           # External metadata APIs (read-only)
│   │   ├── services.py      # api_request() with shared rate-limited Session, ProviderAPIError, get_media_metadata() dispatch
│   │   ├── tmdb.py mal.py igdb.py openlibrary.py hardcover.py comicvine.py mangaupdates.py bgg.py tvdb.py
│   │   └── manual.py        # for user-created "manual" media entries (UUID media_id)
│   ├── views.py             # search, media list, media details, create_entry
│   ├── tasks.py             # core Celery tasks (calendar reload, etc.)
│   ├── signals.py           # SQLite WAL pragma + Celery PENDING TaskResult on publish
│   ├── mixins.py            # CalendarTriggerMixin, disable_fetch_releases context manager
│   ├── middleware.py        # ProviderAPIErrorMiddleware (renders friendly error UI)
│   ├── helpers.py history_processor.py converters.py forms.py admin.py statistics.py templatetags/
│   └── tests/
├── integrations/            # Imports, exports, webhooks (the place Hardcover sync will live)
│   ├── views.py             # OAuth flows for Trakt/Simkl/AniList; webhook receivers; CSV file uploads
│   ├── tasks.py             # @shared_task wrappers around each importer
│   ├── imports/
│   │   ├── trakt.py         # Reference for OAuth-token-based importer with private/public modes
│   │   ├── anilist.py       # Reference for the same pattern (slightly simpler)
│   │   ├── simkl.py mal.py kitsu.py steam.py
│   │   ├── yamtrack.py imdb.py hltb.py goodreads.py    # CSV importers
│   │   ├── helpers.py       # bulk_create_media, bulk_update_media, get_existing_media, encrypt/decrypt, create_import_schedule, MediaImportError/MediaImportUnexpectedError
│   │   └── data/            # static lookup fixtures
│   ├── webhooks/            # base.py, jellyfin.py, plex.py, emby.py
│   ├── exports.py           # streaming CSV writer
│   └── urls.py
├── events/                  # Calendar (.ics), notifications (Apprise), daily digest
├── lists/                   # User-defined collaborative lists
├── users/                   # Custom User model, allauth adapter, user prefs (HomeSort, MediaSort, MediaStatus, Layout choices)
├── templates/               # Django templates; Tailwind classes throughout
│   ├── base.html
│   ├── app/                 # home, media_list, media_details, search, create_entry, statistics, components/
│   ├── users/               # account, preferences, integrations, import_data, export_data, notifications, advanced, about
│   ├── events/ lists/ account/ allauth/ socialaccount/
│   └── 4xx/5xx error pages
└── static/                  # css/, js/libraries/, images
```

## Core data model — read this before touching `app/models.py`

There are two layers, and they must stay separate:

1. **`Item`** (one row per `(media_id, source, media_type)` plus optional season/episode numbers). Holds metadata only: title, image, season/episode numbers. Constraints in `Meta` enforce uniqueness and the season/episode invariants.
2. **`Media`** abstract — concrete subclasses are `TV`, `Season`, `Episode`, `Movie`, `Anime`, `Manga`, `Game`, `Book`, `Comic`, `BoardGame` (plus `BasicMedia` for generic queries via `MediaManager`). Each row links one user to one item with their tracking state: `score` (0–10 decimal), `progress` (PositiveInteger; for `Game` it's minutes), `progressed_at` (auto via `MonitorField(monitor='progress')`), `status` (`Status` text choices: Completed / In progress / Planning / Paused / Dropped), `start_date`, `end_date`, `notes`, plus `created_at` and a `simple_history` audit trail.

Each subclass has `tracker = FieldTracker()` and a wrapping `@tracker` save decorator that runs `process_progress()` and `process_status()` when those fields change. **Don't bypass `Media.save()` for normal updates** — it's where progress→status transitions, end_date stamping, and calendar refresh live. For pure timestamp bookkeeping (e.g., setting a `last_hardcover_sync_at` without firing signals), use `Model.objects.filter(pk=...).update(...)` instead.

`Sources` (TextChoices): `tmdb`, `mal`, `mangaupdates`, `igdb`, `openlibrary`, `hardcover`, `comicvine`, `bgg`, `manual`.

`MediaTypes` (TextChoices): `tv`, `season`, `episode`, `movie`, `anime`, `manga`, `game`, `book`, `comic`, `boardgame`. The `apps.get_model("app", media_type)` pattern is used everywhere — keep these strings stable.

## History-aware bulk operations

`simple_history` patches `Model.bulk_create()` to raise an error: you **must** route bulk writes through `simple_history.utils.bulk_create_with_history` / `bulk_update_with_history` (the `bulk_create_media` / `bulk_update_media` helpers in `integrations/imports/helpers.py` already wrap them). This was issue #337 in the wild. When importing seasons/episodes, also use `update_season_references` / `update_episode_references` to relink unsaved parent FKs — see `helpers.py` for the pattern.

When you *don't* want to disturb the history (e.g., to refresh release data on import), wrap the work in `with disable_fetch_releases():` from `app.mixins`.

## Providers and the shared HTTP session

`app/providers/services.py` owns a single rate-limited `requests` `LimiterSession` shared across all providers, with per-host limiters in Redis. New external HTTP calls should go through `services.api_request(provider, method, url, ...)` rather than calling `requests` directly. On 429 it sleeps for `Retry-After + 3s` and retries once; on other HTTP errors it raises so callers can map them to typed exceptions or `ProviderAPIError`.

`get_media_metadata(media_type, media_id, source, ...)` and `search(media_type, query, page, source=None)` dispatch to the right provider module — books resolve to `hardcover` if `source == 'hardcover'`, otherwise `openlibrary`.

Provider responses are cached in Redis (default 24h via `CACHE_TIMEOUT`). Use `cache_key` strings that include source + media_type + identifier + any pagination args (see `hardcover.search`).

## Integrations and importers

The reference structure for "import data from a third party" is:

- `integrations/imports/<service>.py` — module with an `importer(...)` function that constructs a `<Service>Importer` class instance and returns `(imported_counts: dict[media_type, int], warnings: str)`. See `trakt.py` for OAuth + public modes; `anilist.py` for a simpler OAuth flow.
- `integrations/tasks.py` — `@shared_task(name="Import from <Service>")` wrapper that calls the shared `import_media(...)` helper. The task name string must match what `create_import_schedule` writes into `PeriodicTask.task`.
- `integrations/views.py` — view(s) that handle the OAuth dance / form submission, encrypt the token via `helpers.encrypt`, and either `.delay()` the task or call `helpers.create_import_schedule(...)` for periodic imports.
- `integrations/urls.py` — `path("import/<service>", ...)`.
- `templates/users/import_data.html` — UI tile to start the flow.

Tokens are encrypted at rest with a Fernet key derived from `SECRET_KEY` (`integrations/imports/helpers.py: fernet/encrypt/decrypt`). Don't roll a new crypto scheme.

For webhook-style integrations, see `integrations/webhooks/` (Jellyfin/Plex/Emby) which subclass a common `base.WebhookProcessor`. Auth is by per-user token from `users.models.User.token`.

## Celery

- Two roles: `worker` and `beat`. In production both run via supervisord (see `supervisord.conf`). In dev, run a single process that does both: `celery -A config worker --beat --scheduler django --loglevel DEBUG`.
- `CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"` — schedules live in the DB. New periodic tasks should be created via a data migration with `RunPython`, not pinned in `settings.CELERY_BEAT_SCHEDULE` (that dict is reserved for built-ins like `reload_calendar`, `send_release_notifications`, `send_daily_digest`, `cleanup_user_messages`).
- `CELERY_TASK_TIME_LIMIT = 6h`, `CELERY_TASK_TRACK_STARTED = True`, `CELERY_TASK_SERIALIZER = "pickle"` — required because some imports pickle uploaded files.
- `before_task_publish` signal pre-creates a `TaskResult` row in PENDING state so the UI shows queued work immediately (see `app/signals.py`).
- In tests, `config/test_settings.py` sets `CELERY_TASK_ALWAYS_EAGER = True` so `.delay()` runs inline.

## Settings and secrets

`config/settings.py` reads via `python-decouple`. Every secret has a `default=secret("XXX_FILE", "...")` fallback that reads `/run/secrets/<NAME>_FILE` (Docker secrets pattern). When adding a new env var:

1. Add it to `settings.py` with a sensible default (or `None`) and a `secret()` fallback if it's a real secret.
2. Document it in the wiki page `Environment-Variables.md` (linked from README).
3. If it's user-facing in CI, add it to the `Set environment variables from secrets` step in `.github/workflows/app-tests.yml`.

`URLS=https://yamtrack.example.com[,https://other]` is the canonical "what's our public URL" var — it auto-populates `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. `BASE_URL` is the optional sub-path prefix (e.g., `/yamtrack`).

## Local development

```bash
# Redis
docker run -d --name redis -p 6379:6379 redis:8-alpine

# .env (root) — minimum for full functionality:
TMDB_API=...
MAL_API=...
IGDB_ID=... IGDB_SECRET=...
STEAM_API_KEY=...
BGG_API_TOKEN=...
SECRET=any-string
DEBUG=True

# Setup
python -m pip install -U -r requirements-dev.txt
pre-commit install
cd src
python manage.py migrate

# Run all three in parallel
python manage.py runserver &
celery -A config worker --beat --scheduler django --loglevel DEBUG &
# Tailwind watch — keeps src/static/css/main.css fresh while you edit
# templates / input.css. The pre-commit hook rebuilds on commit too;
# this is just for live-reload during dev.
cd .. && npx tailwindcss -i src/static/css/input.css -o src/static/css/main.css --watch
```

App at http://localhost:8000.

## Testing

```bash
# All tests, parallel (matches CI)
coverage run src/manage.py test app users integrations lists events --parallel
coverage combine && coverage report

# A single app or test
python src/manage.py test integrations.tests.imports.test_trakt
python src/manage.py test integrations.tests.imports.test_trakt.TraktImportTests.test_history
```

Use **Django's test runner**, not bare `pytest`, even though `pytest.ini` and `pytest-django` exist. CI uses `manage.py test`. `pytest.ini` matters for collecting `tests.py` / `test_*.py` / `*_tests.py` and pointing at `config.test_settings`.

When mocking external APIs, use the `responses` library (already a transitive dep). Cassette-style fixtures live alongside the test files in `integrations/tests/imports/` — match the existing pattern.

E2E tests use `pytest-playwright`; CI runs `playwright install` first.

## Linting and formatting

`ruff` config is in `pyproject.toml`: `select = ["ALL"]`, with a small ignore list (notably `ANN`, `PT`, `PD`, `D100/104`, `RUF012`, `PLR0913`, `SLF001`, `COM812`). Migrations are excluded.

`djlint` config (also `pyproject.toml`): `custom_blocks = "element,slot,setvar"`, `preserve_blank_lines = True`, `ignore = "H006,H021"`, indent 2.

Pre-commit runs: `manage.py makemigrations --check` (fails the commit if you forgot a migration), `django-upgrade`, `ruff check --fix`, `ruff format`, `djlint --lint`, `djlint --reformat`.

CI (`app-tests.yml`) runs `ruff check src` and the test suite. **The PR check fails if `.github/workflows/**` was modified** — don't touch those files in feature work; ask before changing.

## Conventions you should follow

- **One module per provider/import source.** Don't mix two services in one file. The convention is "look at `trakt.py`, copy the shape, change the field names."
- **Importers return `(counts_dict, warnings_str)`** so `format_import_message` in `integrations/tasks.py` can format the user-visible message uniformly.
- **`mode` parameter is always one of `"new"` / `"overwrite"`.** Use `helpers.should_process_media` and `helpers.cleanup_existing_media` to handle the two modes consistently.
- **Encrypt OAuth tokens before persisting.** Never store raw tokens in `PeriodicTask.kwargs` or anywhere else.
- **Don't add a default `0`-rating sentinel.** A score of `None` means "no rating"; preserve that on round-trips with external APIs.
- **Templates use Tailwind utility classes directly.** No CSS modules. The custom palette (`bg-[#2a2f35]`, `bg-[#39404b]`, `bg-[#262a2f]`) is repeated by hand — match it.
- **Bumping the service-worker VERSION when shipping static-file changes.** `src/templates/app/serviceworker.js` caches `/static/` assets with a `cacheFirst` strategy (see `cacheFirstStatic`), so a freshly-deployed JS/CSS file *can* keep serving the previous bytes even after YunoHost runs `collectstatic --noinput` — the per-file `?<mtime>` cache-buster in `get_static_file_mtime` doesn't always win (collectstatic preserves source mtimes in some paths, and any browser already running the SW won't re-evaluate cached URLs until the SW version changes). When a feature ship modifies a file under `src/static/js/` or `src/static/css/` (or rewrites template-served JS like the chart files), bump the `const VERSION = 'vN';` line at the top of `serviceworker.js` to `'vN+1'`. The `activate` handler deletes every cache name not in `KEEP`, so all previously-cached static URLs get refetched on the next page load. ~ynh138 → ~ynh139 was the canonical "we forgot this and the new chart JS didn't take effect" example.
- **Django template comments: `{# #}` is single-line only.** Anything that wraps to a second line *leaks* — the second/third lines render as visible text in the page. `djlint` won't catch it. Use `{% comment %} ... {% endcomment %}` for any multi-line note. Before commit/push, run `git diff -- '*.html' | grep -E '^\+.*\{#'` and visually confirm each match is on a single closed line. This has bitten us twice in this branch (ynh102→103, ynh105→106).
- **Don't write new docs unless asked.** Wiki pages live in the upstream `Yamtrack.wiki` repo, not here. Markdown in this tree is rare on purpose.
- **No emojis in code.** README has them; source files don't.
- **Pre-existing models keep `Meta.ordering` and at least one of `UniqueConstraint` / `CheckConstraint`** for safety across SQLite/Postgres — match the style when adding new ones.

## Branching and PR flow (this repo's expectations)

- The integration branch is **`main`**. There is no `dev` branch and no upstream fork — this is a standalone repo. Don't push to or recreate `dev`.
- Develop on the feature branch given in the task brief (e.g., `claude/...` or `feature/...`), branched off `main`. Merge into `main` (fast-forward / linear rebase preferred) as soon as it's ready; don't park work on long-lived branches.
- Always `git fetch origin main && git pull --ff-only` (or `git reset --hard origin/main`) before computing a version bump — containers come up with whatever was cloned at session start.
- Don't `--no-verify` past pre-commit hooks. If `makemigrations --check` fails, run it locally and commit the migration.
- Pushing to `main` is allowed when the user authorizes a release (see "Shipping a release" below).
- `.github/workflows/**` still carries upstream-flavored CI (FuzzyGrim badges/registries, a stale `codeql.yml` branch list). Treat it as out-of-scope tech debt — don't touch it in feature work; ask before reworking it.

## YunoHost package & the bundled source

The packaging lives at the repo root (`manifest.toml`, `scripts/`, `conf/`, `doc/`). The app is **self-contained**: `scripts/install` and `scripts/upgrade` copy the in-repo `src/` + `requirements.txt` into `$install_dir` directly (`pkg_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"`) — there is **no** `[resources.sources]` block, no remote tarball, no `ynh_setup_source`. `backup`/`restore` operate on `$install_dir` as before. If you change how the app is laid out under `src/`, check those two scripts still copy what the app needs at runtime.

## Shipping a release (single repo)

No companion repo, no source-pin, no `~ynhNN` cross-repo alignment anymore. The flow:

1. Land the feature on `main` (rebase + ff-merge preferred). Run the pre-commit hooks; commit any migration.
2. Bump `version` in `manifest.toml` (e.g. `0.25.2~ynh37`). The manifest is the single source of truth for the package version — there is no separate bump-marker commit to keep in sync.
3. If the ship modified files under `src/static/js/` or `src/static/css/` (or template-served JS), bump the service-worker `VERSION` in `src/templates/app/serviceworker.js` (see the Conventions note).
4. `git push origin main`.
5. On the server: `sudo yunohost app upgrade stackwise -u https://github.com/LukeKeller/stackwise_ynh` (or via the admin UI). The upgrade re-copies the bundled `src/`, reinstalls requirements, runs migrations + collectstatic.
6. Delete the feature branch once the upgrade succeeds.

> Moving the live `blog-vps` instance from the old `yamtrack_fork` install to `stackwise` is a one-time **fresh install + Postgres data migration** (a different YunoHost id is a different app), not an in-place upgrade — see the deployment runbook.

## Hardcover sync project (in flight)

This branch is implementing a two-way Hardcover ↔ Stackwise sync. The full plan is in `HARDCOVER_SYNC_PLAN.md` at the repo root — read it before touching any of:

- `src/integrations/imports/hardcover.py` (new — inbound importer, mirror `trakt.py`)
- `src/integrations/hardcover_client.py` / `hardcover_mapping.py` (new — GraphQL wrapper + status/score/date mapping)
- `src/integrations/models.py` (new — `HardcoverIntegration`, `HardcoverBookMapping`, `HardcoverSyncLog`)
- `src/integrations/signals.py` (new — outbound `post_save`/`post_delete` handlers with echo suppression)
- `src/integrations/tasks.py` (extend — `push_book_to_hardcover`, periodic reconciler)
- `src/app/models.py: Book` (add `last_hardcover_sync_at` field — needs a migration)
- `src/app/providers/hardcover.py` (existing read-only metadata provider; can share GraphQL helpers)

The plan covers data model, GraphQL client, field mapping, book identity resolution, echo suppression (the trickiest part — `post_save` from inbound writes will loop into outbound without it), inbound polling, outbound signal-driven sync, scheduling, connect/disconnect UI, env vars, tests, and a phased rollout. Stick to the plan unless you have a concrete reason to deviate; if you do, update `HARDCOVER_SYNC_PLAN.md` so the deviation is recorded.
