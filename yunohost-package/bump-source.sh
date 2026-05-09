#!/usr/bin/env bash
# Update manifest.toml's [resources.sources.main] to point at a different commit
# on LukeKeller/Yamtrack and refresh the matching SHA256.
#
# Usage:
#   ./bump-source.sh                   # use the current git HEAD of the surrounding repo
#   ./bump-source.sh <commit-or-branch> # use the named ref on LukeKeller/Yamtrack
#
# Notes:
#   - The ref must be reachable on https://github.com/LukeKeller/Yamtrack.
#   - For branches, GitHub returns a tarball of the branch tip at fetch time;
#     the SHA256 will reflect that tip and is not stable across pushes.
#     Pinning to a specific commit SHA is the reproducible option.
set -euo pipefail

OWNER="LukeKeller"
REPO="Yamtrack"
MANIFEST="$(dirname "$0")/manifest.toml"

if [[ $# -ge 1 ]]; then
  REF="$1"
else
  REF="$(git -C "$(dirname "$0")" rev-parse HEAD)"
  echo "No ref given; using current repo HEAD: $REF"
fi

# Resolve a branch name to its current commit SHA so the pin is reproducible.
if [[ ! "$REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Resolving '$REF' to a commit SHA via the GitHub API..."
  RESOLVED="$(curl -fsSL "https://api.github.com/repos/$OWNER/$REPO/commits/$REF" \
              | sed -nE 's/^[[:space:]]*"sha":[[:space:]]*"([0-9a-f]{40})".*/\1/p' \
              | head -n1)"
  if [[ -z "$RESOLVED" ]]; then
    echo "ERROR: could not resolve $REF on $OWNER/$REPO" >&2
    exit 1
  fi
  echo "  -> $RESOLVED"
  REF="$RESOLVED"
fi

URL="https://github.com/$OWNER/$REPO/archive/$REF.tar.gz"
echo "Fetching $URL ..."
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$URL" -o "$TMP"
SHA256="$(sha256sum "$TMP" | cut -d' ' -f1)"
echo "SHA256: $SHA256"

python3 - "$MANIFEST" "$URL" "$SHA256" <<'PY'
import re
import sys
from pathlib import Path

manifest_path, url, sha256 = sys.argv[1], sys.argv[2], sys.argv[3]
text = Path(manifest_path).read_text()

text = re.sub(
    r'(\[resources\.sources\.main\][^\[]*?url\s*=\s*)"[^"]*"',
    lambda m: f'{m.group(1)}"{url}"',
    text,
    count=1,
    flags=re.DOTALL,
)
text = re.sub(
    r'(\[resources\.sources\.main\][^\[]*?sha256\s*=\s*)"[^"]*"',
    lambda m: f'{m.group(1)}"{sha256}"',
    text,
    count=1,
    flags=re.DOTALL,
)

Path(manifest_path).write_text(text)
PY

echo
echo "manifest.toml updated. Diff:"
git --no-pager -C "$(dirname "$0")" diff -- manifest.toml || true
