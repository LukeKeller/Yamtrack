#!/usr/bin/env bash
# Deterministic color-token sweep: maps raw Tailwind palette utilities onto
# the semantic design tokens. Idempotent — token names contain no palette
# color names, so re-running never double-converts. Operates on the files
# passed as args (default: all templates).
set -euo pipefail

files=("$@")
if [[ ${#files[@]} -eq 0 ]]; then
  mapfile -t files < <(grep -rEl \
    "(indigo|gray|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|violet|purple|fuchsia|pink|rose)-[0-9]" \
    src/templates --include=*.html)
fi

for f in "${files[@]}"; do
  [[ -f "$f" ]] || continue
  sed -i -E \
    `# brand accent (indigo) -> accent tokens` \
    -e 's/-indigo-700/-accent-hover/g' \
    -e 's/-indigo-600/-accent-strong/g' \
    -e 's/-indigo-500/-accent-strong/g' \
    -e 's/-indigo-400/-accent/g' \
    -e 's/-indigo-300/-accent/g' \
    -e 's/-indigo-200/-accent/g' \
    `# neutrals (gray) -> surface / fg / border` \
    -e 's/bg-gray-900/bg-surface-0/g' \
    -e 's/bg-gray-800/bg-surface-1/g' \
    -e 's/bg-gray-700/bg-surface-2/g' \
    -e 's/bg-gray-600/bg-surface-3/g' \
    -e 's/bg-gray-500/bg-surface-4/g' \
    -e 's/border-gray-700/border-default/g' \
    -e 's/border-gray-600/border-strong/g' \
    -e 's/border-gray-300/border-strong/g' \
    -e 's/text-gray-400/text-fg-muted/g' \
    -e 's/text-gray-500/text-fg-faint/g' \
    -e 's/text-gray-300/text-fg-muted/g' \
    -e 's/text-gray-200/text-fg/g' \
    -e 's/text-gray-600/text-fg-muted/g' \
    -e 's/text-gray-700/text-fg-muted/g' \
    -e 's/fill-gray-400/fill-fg-faint/g' \
    `# status foregrounds / icons` \
    -e 's/text-(red|rose)-[0-9]+/text-danger/g' \
    -e 's/text-(amber|yellow|orange)-[0-9]+/text-warning/g' \
    -e 's/text-(emerald|green|lime|teal)-[0-9]+/text-success/g' \
    -e 's/text-(sky|blue|cyan)-[0-9]+/text-info/g' \
    -e 's/text-(purple|violet|fuchsia|pink)-[0-9]+/text-accent/g' \
    -e 's/fill-(amber|yellow|orange)-[0-9]+/fill-warning/g' \
    -e 's/fill-(emerald|green)-[0-9]+/fill-success/g' \
    `# status borders / rings / gradients` \
    -e 's/border-(red|rose)-[0-9]+/border-danger/g' \
    -e 's/border-(amber|yellow|orange)-[0-9]+/border-warning/g' \
    -e 's/border-(emerald|green)-[0-9]+/border-success/g' \
    -e 's/border-(sky|blue|cyan)-[0-9]+/border-info/g' \
    -e 's/ring-(red|rose)-[0-9]+/ring-danger/g' \
    -e 's/ring-(emerald|green)-[0-9]+/ring-success/g' \
    -e 's/ring-(sky|blue|cyan)-[0-9]+/ring-info/g' \
    -e 's/(from|via|to)-(sky|blue|cyan)-[0-9]+/\1-info/g' \
    `# alert banner bg + non-white-text soft tints / dots` \
    -e 's#bg-(red|rose)-900/[0-9]+#bg-danger-soft#g' \
    -e 's#bg-(red|rose)-400(/[0-9]+)?#bg-danger\2#g' \
    -e 's#bg-(red|rose)-600/(10|15|20|25)#bg-danger/\2#g' \
    -e 's#bg-(amber|yellow)-400(/[0-9]+)?#bg-warning\2#g' \
    -e 's#bg-amber-500(/[0-9]+)?#bg-warning\1#g' \
    -e 's#bg-yellow-600/(10|15|20|25)#bg-warning/\1#g' \
    -e 's#bg-(emerald|green|lime)-400(/[0-9]+)?#bg-success\2#g' \
    -e 's#bg-emerald-600/(10|15|20|25)#bg-success/\1#g' \
    -e 's#bg-(sky|cyan)-400(/[0-9]+)?#bg-info\2#g' \
    -e 's#bg-blue-400(/[0-9]+)?#bg-info\1#g' \
    `# stray hex literals -> tokens` \
    -e 's/ring-\[#4a9eff\]/ring-accent/g' \
    -e 's/divide-\[#39404b\]/divide-border-default/g' \
    "$f"
done
echo "swept ${#files[@]} file(s)"
