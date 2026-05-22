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
  mapfile -t files < <(find src/templates -name '*.html' -type f)
else
  files=("$@")
fi

bad=0
for f in "${files[@]}"; do
  [[ -f $f ]] || continue
  [[ $f == *.html ]] || continue
  # Match lines that open `{#` but have no matching `#}` AFTER the open.
  # `[^{]` lookbehind via grep -P excludes the Handlebars-style `{{#…}}`
  # tag used in users/integrations.html's webhook payload templates.
  matches=$(grep -nP '(?<!\{)\{#[^#]*$' "$f" || true)
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