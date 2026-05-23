#!/usr/bin/env bash
# Idempotent local-dev provisioner. Re-running is safe.
#
# Provides: a Python 3.12 virtualenv at ./.venv, all project deps from
# requirements-dev.txt, pre-commit hooks installed, a yamtrack-redis docker
# container running on 6379, a .env file seeded from .env.example, and a
# fresh `manage.py migrate`. Tailwind is rebuilt at the end so main.css is
# in sync with templates.
#
# Run once:   ./scripts/dev-setup.sh
# Then per session:
#     source .venv/bin/activate
#     python src/manage.py runserver
#     ./build-css.sh

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say() { printf '\033[1;36m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# --- Locate Python -----------------------------------------------------
# Django 5.2 supports 3.10-3.13; the project targets 3.12. We accept 3.12
# or 3.13 (most wheels available) and refuse anything else so a fresh
# Python 3.14 system install doesn't break dependency installs.
PYTHON_BIN=""
for candidate in python3.12 python3.13; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if [[ "$version" == "3.12" || "$version" == "3.13" ]]; then
            PYTHON_BIN="python3"
        fi
    fi
fi

if [[ -z "$PYTHON_BIN" ]]; then
    die "Need Python 3.12 or 3.13. On macOS:  brew install python@3.12"
fi

say "Using $PYTHON_BIN ($($PYTHON_BIN --version))"

# --- Virtualenv --------------------------------------------------------
if [[ ! -d .venv ]]; then
    say "Creating .venv"
    "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

say "Upgrading pip + wheel"
python -m pip install --upgrade --quiet pip wheel

say "Installing requirements-dev.txt (this is the slow step)"
python -m pip install --quiet -r requirements-dev.txt

# --- pre-commit hooks --------------------------------------------------
say "Installing pre-commit hooks"
pre-commit install

# --- Redis -------------------------------------------------------------
# Non-fatal: if the Docker daemon isn't running, warn and continue. Tests
# work via fakeredis; only `runserver` needs a real redis. The user can
# start Docker Desktop and re-run this script later.
start_redis() {
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not installed — runserver will fail. Tests still work via fakeredis."
        return 0
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "Docker daemon not running. Start Docker Desktop then re-run this script."
        return 0
    fi
    if docker ps --filter name=^yamtrack-redis$ --format '{{.Names}}' | grep -q yamtrack-redis; then
        say "Redis already running (yamtrack-redis)"
    elif docker ps -a --filter name=^yamtrack-redis$ --format '{{.Names}}' | grep -q yamtrack-redis; then
        say "Starting existing yamtrack-redis container"
        docker start yamtrack-redis >/dev/null
    else
        say "Launching yamtrack-redis (redis:8-alpine on 6379)"
        docker run -d --name yamtrack-redis -p 6379:6379 redis:8-alpine >/dev/null
    fi
}
start_redis || true

# --- .env --------------------------------------------------------------
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example .env
        say "Created .env from .env.example"
    else
        die ".env.example missing — repo state is broken"
    fi
else
    say ".env present, leaving alone"
fi

# --- Migrations --------------------------------------------------------
say "Running migrate"
( cd src && python manage.py migrate --no-input )

# --- Tailwind ----------------------------------------------------------
if command -v npx >/dev/null 2>&1; then
    say "Rebuilding Tailwind"
    ./build-css.sh
else
    warn "npx not on PATH — install node and run ./build-css.sh manually"
fi

cat <<'EOF'

✓ Setup complete.

Next session, activate the venv and you're ready:

    source .venv/bin/activate
    python src/manage.py runserver
    python src/manage.py test app
    ./build-css.sh

Pre-commit will now run ruff/djlint/migrations-check/Tailwind on every
commit. To run them manually:  pre-commit run --all-files
EOF
