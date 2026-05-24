#!/usr/bin/env bash
# Refuse to commit a Django template that opens `{#` without closing `#}` on
# the same line.
#
# Django's `{# … #}` comment syntax is single-line ONLY. Multi-line spans
# render as literal text to the user. We keep regressing this in template
# edits — this hook catches it before commit.
#
# Multi-line block comments belong in `{% comment %} … {% endcomment %}`.
#
# Usage:
#   ./scripts/check-multiline-comments.sh [path …]
#
# Pre-commit calls us with the staged file list; with no args we scan the
# whole templates tree.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  # macOS's bundled bash 3.2 doesn't have `mapfile`; use a portable loop.
  files=()
  while IFS= read -r f; do
    files+=("$f")
  done < <(find src/templates -name '*.html' -type f)
else
  files=("$@")
fi

bad=0
# Drive the scan with Python rather than grep so we're not dependent on
# the host having GNU grep -P (BSD grep on macOS doesn't). The previous
# shell version silently passed on macOS because `grep -P` errored out
# and `|| true` swallowed it — regressions slipped through pre-commit.
for f in "${files[@]}"; do
  [[ -f $f ]] || continue
  [[ $f == *.html ]] || continue
  matches=$(python3 - "$f" <<'PY'
import re
import sys

# A bad opener: `{#` not preceded by another `{` (so we don't catch the
# Handlebars-style `{{#…}}` used in users/integrations.html), and with
# no matching `#}` later on the same line.
pattern = re.compile(r"(?<!\{)\{#(?![^#\n]*#\})")
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    for lineno, line in enumerate(fh, 1):
        if pattern.search(line):
            print(f"{lineno}:{line.rstrip()}")
PY
)
  if [[ -n $matches ]]; then
    echo "$f:"
    echo "$matches" | sed 's/^/  /'
    bad=$((bad + 1))
  fi
done

if [[ $bad -gt 0 ]]; then
  cat >&2 <<EOF

ERROR: $bad template(s) contain a multi-line {# … #} comment.

Django's {# #} only supports SINGLE-LINE comments — multi-line blocks
render as visible text in the rendered HTML. Replace with:

  {% comment %}
    your multi-line
    explanation
  {% endcomment %}

EOF
  exit 1
fi