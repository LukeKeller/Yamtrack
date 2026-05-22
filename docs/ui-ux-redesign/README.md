# Yamtrack — UI/UX Audit & Redesign

This folder is a self-contained research package: an exhaustive audit of
the current Yamtrack UI, a comparison against modern media-tracker
conventions, a proposed design system, a phased implementation plan, and
a gallery of HTML mocks showing the target look and feel.

Nothing here changes runtime behavior — the live app still renders the
templates under `src/templates/`. The mocks live under `mocks/` and are
plain static HTML you can open in a browser (each pulls Tailwind v3 via
CDN so the visual approximations are accurate without a build step).

## Table of contents

| Doc | What's inside |
| --- | --- |
| [01-current-state-audit.md](./01-current-state-audit.md) | Per-screen breakdown of today's UI — layout, components, palette, behavior, friction points |
| [02-modern-standards.md](./02-modern-standards.md) | Conventions in 2026 media trackers (Letterboxd, Trakt, AniList, Plex, Backloggd, Discogs, StoryGraph) and what Yamtrack does and doesn't pick up |
| [03-design-system.md](./03-design-system.md) | Proposed design tokens, typography, spacing, color, status & media-type semantics, motion |
| [04-redesign-plan.md](./04-redesign-plan.md) | Phased roadmap with file-level scope and effort estimates |
| [05-user-flows.md](./05-user-flows.md) | Flow diagrams for the seven flows the redesign is optimizing for |

## Viewing the mocks rendered (not as source)

**Why GitHub's "Raw" link shows source:** GitHub serves `.html` files
from `raw.githubusercontent.com` with `Content-Type: text/plain;
charset=utf-8` for security. Firefox / Chrome respect that header and
display the source rather than rendering. There are three ways to see
the rendered output:

### Option A — raw.githack.com (recommended, no setup)

`raw.githack.com` is a free proxy that serves the same files with the
correct MIME type. Open the gallery here:

**▶ [Open the mock gallery (raw.githack.com)](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/index.html)**

The internal links between mocks (e.g. the gallery → `home.html` → the
sidebar links) all resolve under the same proxy, so navigating between
mocks works once you start from the gallery. Direct links to each
mock:

| Mock | Link |
| --- | --- |
| Gallery (start here) | [index.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/index.html) |
| Home — authenticated | [home.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/home.html) |
| Home — empty / first run | [home-empty.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/home-empty.html) |
| Onboarding wizard | [onboarding.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/onboarding.html) |
| Media list — grid | [media-list-grid.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/media-list-grid.html) |
| Media list — table | [media-list-table.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/media-list-table.html) |
| Movie detail | [media-details-movie.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/media-details-movie.html) |
| TV detail | [media-details-tv.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/media-details-tv.html) |
| Search | [search.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/search.html) |
| Calendar | [calendar.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/calendar.html) |
| Lists | [lists.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/lists.html) |
| List detail | [list-detail.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/list-detail.html) |
| Statistics | [statistics.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/statistics.html) |
| Settings | [settings.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/settings.html) |
| Login | [login.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/login.html) |
| Command palette (⌘K) | [command-palette.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/command-palette.html) |
| Track drawer | [track-drawer.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/track-drawer.html) |
| Mobile home | [mobile-home.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/mobile-home.html) |
| Mobile detail | [mobile-details.html](https://raw.githack.com/LukeKeller/Yamtrack/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/mobile-details.html) |

raw.githack.com caches with `s-maxage=300`; if you push a fix and the
old version sticks, use the **rawcdn.githack.com** variant (longer
cache, permalink-style) by swapping the hostname, or hard-refresh.

### Option B — htmlpreview.github.io

A second free proxy with the same intent. Less smooth at relative
links (it rewrites them), but useful as a backup:

`https://htmlpreview.github.io/?https://github.com/LukeKeller/Yamtrack/blob/claude/ui-ux-audit-redesign-UFa0c/docs/ui-ux-redesign/mocks/<name>.html`

### Option C — enable GitHub Pages on this branch

```
Settings → Pages → Source: claude/ui-ux-audit-redesign-UFa0c → /docs
```

That serves the docs folder at
`https://lukekeller.github.io/Yamtrack/ui-ux-redesign/mocks/index.html`
without a third-party proxy. Choose this for sharing with anyone else
since the URL is yours.

### Option D — clone and open locally

```
git clone https://github.com/LukeKeller/Yamtrack.git
cd Yamtrack && git checkout claude/ui-ux-audit-redesign-UFa0c
open docs/ui-ux-redesign/mocks/index.html   # macOS
xdg-open docs/ui-ux-redesign/mocks/index.html  # Linux
```

## Mocks (source links)

If you just want to read the source rather than render it, the GitHub
links are below. The README at the top of this file is what you see on
GitHub; the rendered output lives behind the raw.githack.com links
above.

- `mocks/index.html` — gallery
- `mocks/home.html`, `mocks/home-empty.html`
- `mocks/onboarding.html`, `mocks/login.html`
- `mocks/media-list-grid.html`, `mocks/media-list-table.html`
- `mocks/media-details-movie.html`, `mocks/media-details-tv.html`
- `mocks/search.html`, `mocks/calendar.html`
- `mocks/lists.html`, `mocks/list-detail.html`
- `mocks/statistics.html`, `mocks/settings.html`
- `mocks/command-palette.html`, `mocks/track-drawer.html`
- `mocks/mobile-home.html`, `mocks/mobile-details.html`
- `mocks/_assets/tokens.css` — design tokens shared across every mock

## What the redesign is — and isn't

**Is:** a Tailwind/Alpine/HTMX-native evolution. Same stack, same
templating, same Django views. The goal is to harvest the patterns that
make Letterboxd/Trakt/Plex feel modern and apply them inside Yamtrack's
existing technical constraints, while normalizing the design language
(tokens, motion, status semantics) so themes don't fight the templates.

**Isn't:** a React/Vue rewrite, a backend redesign, or a feature
expansion. New patterns (command palette, bottom nav, drawer) are
additive; the underlying data model and view hierarchy stay put.

## How to read this

If you only have ten minutes, read sections **TL;DR** at the top of
[01-current-state-audit.md](./01-current-state-audit.md) and
[04-redesign-plan.md](./04-redesign-plan.md), then open
[home.html](./mocks/home.html) and
[media-details-movie.html](./mocks/media-details-movie.html). That gets
you the diagnosis, the prescription, and a visual anchor.

If you have an hour, read top-to-bottom and click through every mock.
