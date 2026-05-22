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

## Mocks

Open `mocks/index.html` in a browser for the gallery, or jump directly to
any of these (Tailwind v3 CDN is loaded inline):

- [home.html](./mocks/home.html) — authenticated home, with the new "Up next" + activity feed
- [home-empty.html](./mocks/home-empty.html) — empty / first-run home
- [onboarding.html](./mocks/onboarding.html) — 3-step setup wizard
- [media-list-grid.html](./mocks/media-list-grid.html) — TV list in grid layout
- [media-list-table.html](./mocks/media-list-table.html) — TV list in dense table layout
- [media-details-movie.html](./mocks/media-details-movie.html) — movie detail with hero/backdrop
- [media-details-tv.html](./mocks/media-details-tv.html) — TV detail with seasons & episodes
- [search.html](./mocks/search.html) — search results with quick-add
- [calendar.html](./mocks/calendar.html) — calendar with month + agenda views
- [lists.html](./mocks/lists.html) — custom lists overview
- [list-detail.html](./mocks/list-detail.html) — single list view
- [statistics.html](./mocks/statistics.html) — stats with a "year in review" hero
- [settings.html](./mocks/settings.html) — settings shell with tabs
- [login.html](./mocks/login.html) — login screen
- [command-palette.html](./mocks/command-palette.html) — ⌘K overlay
- [track-drawer.html](./mocks/track-drawer.html) — tracking drawer (replaces modal)
- [mobile-home.html](./mocks/mobile-home.html) — mobile home with bottom nav
- [mobile-details.html](./mocks/mobile-details.html) — mobile detail page

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
