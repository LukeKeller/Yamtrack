# Stackwise

![License](https://img.shields.io/badge/license-AGPL--3.0-blue)

Stackwise is a self-hosted media tracker for movies, TV shows, anime, manga, video games, books, comics, and board games.

This repository is **self-contained**: it holds both the Django application (`src/`) and its YunoHost package (`manifest.toml`, `scripts/`, `conf/`). There is no separate packaging repo and no upstream sync — installing the YunoHost app deploys exactly the code in this repo.

## Relationship to Yamtrack

Stackwise began as a fork of [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) by FuzzyGrim and has since evolved into its own project. It remains a derivative work distributed under the **AGPL-3.0** license; upstream attribution and the license notice are preserved in the app's About page. The "Import from Yamtrack" feature reads the upstream app's CSV/backup export and is named accordingly.

## Naming convention (read before renaming anything)

- **User-facing identity is "Stackwise"** — the brand shown in the UI, the PWA name, the YunoHost app (`id = stackwise`, installed at `/stackwise`), and the systemd service descriptions.
- **Internal identifiers stay `yamtrack`** — the Django app, the Celery app name (`Celery("yamtrack")`), Python module paths, database tables, the service-worker cache keys, the `yamtrackAppearance` localStorage keys, and the `YAMTRACK_PYTHON_*` / `yamtrack_*` helpers in the install scripts. Renaming these buys nothing user-visible and would force data migrations, reset saved preferences, or orphan Celery tasks. **Leave them as `yamtrack`.**

When in doubt: if a user or the server operator sees it, it's "Stackwise"; if only the code sees it, it stays `yamtrack`.

## Features

- 🎬 Track movies, TV shows, anime, manga, games, books, comics, and board games.
- 📺 Track each season of a TV show individually and episodes watched.
- ⭐ Save score, status, progress, repeats, start/end dates, or write a note.
- 📈 Keep a tracking history of every action on a media item.
- ✏️ Create custom media entries for niche media not covered by the supported APIs.
- 📂 Create personal lists and collaborate with other members.
- 📅 Calendar of upcoming media, subscribable via iCalendar (.ics).
- 🔔 Upcoming-release notifications via Apprise (Discord, Telegram, ntfy, Slack, email, and more).
- 🐳 Docker deployment via docker-compose with SQLite or PostgreSQL.
- 👥 Multi-user accounts with personalized tracking.
- 🔑 OIDC and 100+ social providers (Google, GitHub, Discord, etc.) via django-allauth.
- 🦀 Jellyfin / Plex / Emby integration to auto-track watched media.
- 📥 Import from Trakt, Simkl, MyAnimeList, AniList, Kitsu, and Yamtrack (CSV), with periodic auto-imports.
- 📊 Export all tracked media to CSV and import it back.

## Installing on YunoHost (recommended)

The package is self-contained — the app code is bundled in this repo and copied into place by the install script (no remote tarball, no version pinning).

```bash
sudo yunohost app install https://github.com/LukeKeller/stackwise_ynh
```

This installs the app with YunoHost id `stackwise` at the `/stackwise` path by default (configurable at install time). Optional SSO via Dex/OIDC is supported — see `doc/PRE_INSTALL.md`. Operational details (Postgres, Celery services, OIDC) are in [`YUNOHOST_DEPLOYMENT.md`](YUNOHOST_DEPLOYMENT.md).

## Installing with Docker

Copy `docker-compose.yml` from the repository and set the environment variables (SQLite by default, which is enough for most use cases):

```bash
docker-compose up -d
```

Use `docker-compose.postgres.yml` if you need PostgreSQL.

### Reverse proxy

Set the `URLS` environment variable to the public URL so the app trusts the proxy origin and generates correct URLs for OAuth redirects and webhooks:

```yaml
services:
  stackwise:
    ...
    environment:
      - URLS=https://stackwise.mydomain.com
```

Include the protocol (`https`/`http`) and no trailing context path. Separate multiple origins with commas.

## Local development

```bash
git clone https://github.com/LukeKeller/stackwise_ynh.git
cd stackwise_ynh

# Redis
docker run -d --name redis -p 6379:6379 --restart unless-stopped redis:8-alpine

# .env in the repo root
cat > .env <<'EOF'
TMDB_API=API_KEY
MAL_API=API_KEY
IGDB_ID=IGDB_ID
IGDB_SECRET=IGDB_SECRET
STEAM_API_KEY=STEAM_API_KEY
BGG_API_TOKEN=BGG_API_TOKEN
SECRET=any-string
DEBUG=True
EOF

python -m pip install -U -r requirements-dev.txt
pre-commit install
cd src
python manage.py migrate
python manage.py runserver & \
  celery -A config worker --beat --scheduler django --loglevel DEBUG & \
  npx tailwindcss -i ./static/css/input.css -o ./static/css/main.css --watch
```

App at http://localhost:8000. See [`CLAUDE.md`](CLAUDE.md) for architecture and conventions.

## License

AGPL-3.0-or-later. As a derivative of Yamtrack, Stackwise preserves upstream copyright and the AGPL notice; if you redistribute a modified build (including a modified Docker image), you must make the corresponding source available under the same license.
