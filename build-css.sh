#!/usr/bin/env bash
# Compile src/static/css/input.css → src/static/css/main.css with Tailwind v4.
#
# Used by:
#   - The pre-commit hook (`tailwind-build` in .pre-commit-config.yaml) to
#     keep the committed main.css in sync with input.css and template class
#     usage. The compiled CSS is a build artifact but lives in git because
#     neither the Dockerfile nor the YunoHost installer re-runs Tailwind.
#   - Devs who want to refresh the CSS manually before pushing.
#
# Idempotent: if tailwindcss is already installed under ./node_modules, no
# npm install runs. First invocation installs the deps once.
#
# Requires: node (and bundled npm). Tested with node 20+.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if ! command -v node >/dev/null 2>&1; then
  echo "build-css.sh: 'node' not found on PATH." >&2
  echo "  Install Node.js (any 20+ release works) and re-run." >&2
  exit 1
fi

if [[ ! -d node_modules/tailwindcss ]]; then
  echo "build-css.sh: installing tailwindcss locally (one-time)..."
  npm install --no-save --no-audit --no-fund --silent \
    tailwindcss@4 @tailwindcss/cli@4 >/dev/null
fi

INPUT="src/static/css/input.css"
OUTPUT="src/static/css/main.css"

# Capture the prior contents so we can tell pre-commit whether anything
# actually changed; this keeps the hook exit code meaningful for CI.
PREV_HASH=""
if [[ -f "$OUTPUT" ]]; then
  PREV_HASH=$(sha256sum "$OUTPUT" | cut -d' ' -f1)
fi

npx tailwindcss -i "$INPUT" -o "$OUTPUT" "$@"

NEW_HASH=$(sha256sum "$OUTPUT" | cut -d' ' -f1)
if [[ "$PREV_HASH" != "$NEW_HASH" ]]; then
  # Stage the rebuilt CSS so the commit includes it.
  git add "$OUTPUT" 2>/dev/null || true
  echo "build-css.sh: $OUTPUT updated and staged."
else
  echo "build-css.sh: $OUTPUT already up to date."
fi
