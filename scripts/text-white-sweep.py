#!/usr/bin/env python3
"""Map text-white -> text-fg only inside class attributes that paint a neutral
surface (inputs/panels/cards). White on scrims/accent fills/covers is left
intact, and Alpine :class / x-bind:class dynamic attrs are skipped. Idempotent.

Usage: text-white-sweep.py [files...]   (default: all templates)
"""
import re
import sys
import glob

# Static class="..." only (exclude :class / @class / x-bind:class via the char
# immediately before "class"); Django's add_class:"..." filter is included.
ATTR_RE = re.compile(r'(?<![:@])class="([^"]*)"')
TW_RE = re.compile(r"\btext-white\b")


def convert(path: str) -> int:
    src = open(path, encoding="utf-8").read()
    n = [0]

    def repl(m: re.Match) -> str:
        body = m.group(1)
        if ("bg-surface-" in body or "bg-canvas" in body) and "text-white" in body:
            new = TW_RE.sub("text-fg", body)
            if new != body:
                n[0] += 1
                return 'class="' + new + '"'
        return m.group(0)

    out = ATTR_RE.sub(repl, src)
    if n[0]:
        open(path, "w", encoding="utf-8").write(out)
    return n[0]


def main() -> None:
    files = sys.argv[1:] or glob.glob("src/templates/**/*.html", recursive=True)
    total = sum(convert(f) for f in files)
    print(f"text-white -> text-fg: {total} attrs across {len(files)} file(s)")


if __name__ == "__main__":
    main()
