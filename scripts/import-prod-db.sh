#!/usr/bin/env bash
# Restore a production pg_dump into a local Postgres container so the
# local instance has realistic data to iterate on. Idempotent.
#
# Usage:
#     ./scripts/import-prod-db.sh path/to/yamtrack-prod.dump
#
# What it does:
#   - Starts (or restarts) a yamtrack-pg docker container on 5432.
#   - Drops + recreates the yamtrack database inside it.
#   - Restores the supplied dump.
#   - Writes the DB_* lines into .env (preserving everything else).
#   - Runs `manage.py migrate` so any schema deltas from dev land cleanly.
#
# Not handled (do these yourself if needed):
#   - SECRET parity. OAuth tokens etc. were encrypted with the VPS
#     SECRET_KEY; copy that into .env if you want integrations to work.
#   - Local user password. After import, run:
#         .venv/bin/python src/manage.py changepassword <username>

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $# -ne 1 || ! -f "$1" ]]; then
    echo "Usage: $0 <path-to-yamtrack-prod.dump>" >&2
    exit 1
fi
DUMP_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"

say() { printf '\033[1;36m→\033[0m %s\n' "$*"; }

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "Docker daemon must be running." >&2
    exit 1
fi

PG_CONTAINER=yamtrack-pg
PG_USER=yamtrack
PG_PASSWORD=yamtrack
PG_DB=yamtrack

# --- Container -----------------------------------------------------------
if docker ps --filter "name=^${PG_CONTAINER}$" --format '{{.Names}}' | grep -q "$PG_CONTAINER"; then
    say "Postgres container already running ($PG_CONTAINER)"
elif docker ps -a --filter "name=^${PG_CONTAINER}$" --format '{{.Names}}' | grep -q "$PG_CONTAINER"; then
    say "Starting existing $PG_CONTAINER"
    docker start "$PG_CONTAINER" >/dev/null
else
    say "Launching $PG_CONTAINER (postgres:16-alpine on 5432)"
    docker run -d --name "$PG_CONTAINER" \
        -e POSTGRES_USER="$PG_USER" \
        -e POSTGRES_PASSWORD="$PG_PASSWORD" \
        -e POSTGRES_DB="$PG_DB" \
        -p 5432:5432 \
        postgres:16-alpine >/dev/null
fi

# Wait for it to accept connections
say "Waiting for Postgres to accept connections..."
for _ in {1..30}; do
    if docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# --- Drop + recreate the target DB --------------------------------------
say "Dropping + recreating $PG_DB"
docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS $PG_DB WITH (FORCE);" \
    -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" >/dev/null

# --- Restore ------------------------------------------------------------
say "Restoring $DUMP_PATH"
docker cp "$DUMP_PATH" "$PG_CONTAINER:/tmp/import.dump"
docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
    pg_restore -U "$PG_USER" -d "$PG_DB" --no-owner --no-acl \
    /tmp/import.dump 2>&1 | tail -5 || true

# --- Update .env ---------------------------------------------------------
say "Updating .env to point at the local Postgres"
touch .env
python3 - "$PG_USER" "$PG_PASSWORD" "$PG_DB" <<'PY'
import sys, pathlib
user, pwd, db = sys.argv[1], sys.argv[2], sys.argv[3]
env_path = pathlib.Path('.env')
lines = [ln for ln in env_path.read_text().splitlines() if not ln.startswith('DB_')]
lines += [
    'DB_HOST=localhost',
    'DB_PORT=5432',
    f'DB_NAME={db}',
    f'DB_USER={user}',
    f'DB_PASSWORD={pwd}',
]
env_path.write_text('\n'.join(lines).rstrip() + '\n')
PY

# --- Migrate to align schema -------------------------------------------
if [[ -d .venv ]]; then
    say "Running migrate to align schema"
    .venv/bin/python src/manage.py migrate --no-input
else
    echo "(.venv missing — run ./scripts/dev-setup.sh first to apply migrations)"
fi

cat <<EOF

✓ Import complete. Next:

    .venv/bin/python src/manage.py runserver
    # Browse with your existing VPS credentials, or reset locally with:
    .venv/bin/python src/manage.py changepassword <username>

If integrations need to work locally, copy your VPS \`SECRET\` into .env
so encrypted OAuth tokens decrypt. Otherwise the UI renders fine and
only integration flows will silently fail.
EOF
