# 03 — Design system

The tokens, types, components, and motion specs the redesign uses.
Everything here is captured in `mocks/_assets/tokens.css` so the mocks
render the real thing. When the redesign ships, these become CSS
custom properties in the Tailwind theme layer.

## Design principles

1. **One primary action per surface.** Every screen has a single
   highest-weight CTA. Secondary actions go in overflow menus or
   reveal on hover.
2. **Color is information, not decoration.** Each accent has a job:
   indigo for brand, status colors for status, type colors for type.
   No "let's make this button purple because it's different".
3. **Type carries hierarchy, not boxes.** Two paragraphs of different
   size and weight communicate "title vs metadata" better than two
   panels of different background.
4. **Surfaces stay quiet.** The slate palette steps are narrow on
   purpose — a card barely lifts off the page. Density and typography
   do the work.
5. **Motion explains transitions, not personality.** 150-200 ms eases.
   No bouncy springs. Reduced-motion media query disables everything
   non-essential.
6. **Keyboard parity.** Every mouse-driven action has a keyboard
   equivalent. Tab order is meaningful.
7. **Themes don't fight templates.** Templates reference semantic
   tokens (`bg-surface-1`, `text-muted`); themes redefine the tokens.
   Adding a new theme is a 30-line CSS file, not 19 hex-bracket
   overrides.

## Color tokens

All colors are defined as CSS custom properties on `:root` and
re-defined per theme on `html[data-theme="..."]`. Tailwind reads these
via `@theme` block in `input.css` and exposes them as utilities
(`bg-surface-1`, `text-fg-muted`, etc.).

### Surfaces (slate palette steps)

```
--bg:           #0d0f12   /* page background, lowest */
--surface-0:    #14171c   /* sidebar, top bar */
--surface-1:    #1c2027   /* card */
--surface-2:    #252a33   /* input, secondary button */
--surface-3:    #2f3540   /* hover, selected */
--surface-4:    #3a414e   /* active, focused row */
```

### Borders & dividers

```
--border-subtle:  rgba(255, 255, 255, 0.04)
--border:         rgba(255, 255, 255, 0.08)
--border-strong:  rgba(255, 255, 255, 0.14)
```

### Foreground (text)

```
--fg:        #ecedf0  /* primary text */
--fg-muted:  #a4abb6  /* secondary text, metadata */
--fg-faint:  #6b7383  /* tertiary, placeholders */
--fg-disabled: #4a5163
```

### Accent (brand)

```
--accent:        oklch(58.5% 0.233 277.117)  /* indigo-500 */
--accent-strong: oklch(51.1% 0.262 276.966)  /* indigo-600 (CTAs) */
--accent-hover:  oklch(45.7% 0.240 277.023)  /* indigo-700 (hover) */
--accent-soft:   oklch(58.5% 0.233 277.117 / 0.16)  /* tinted bg */
--accent-fg:     #ffffff  /* text on accent */
```

### Status (semantic)

Used as a tint background + bold-color foreground for pills, and as a
solid background for state indicators. Each status maps to one hue.

```
--status-completed:    oklch(70% 0.16 165)   /* emerald-400 */
--status-completed-bg: oklch(70% 0.16 165 / 0.14)
--status-in-progress:  oklch(73% 0.17 230)   /* sky-400 */
--status-in-progress-bg: oklch(73% 0.17 230 / 0.14)
--status-planning:     oklch(78% 0.10 250)   /* indigo-300 */
--status-planning-bg:  oklch(78% 0.10 250 / 0.14)
--status-paused:       oklch(80% 0.16 80)    /* amber-300 */
--status-paused-bg:    oklch(80% 0.16 80 / 0.14)
--status-dropped:      oklch(70% 0.18 25)    /* rose-400 */
--status-dropped-bg:   oklch(70% 0.18 25 / 0.14)
```

### Media-type accents (subtle, decorative)

A 1-2 px border or a small dot. Never a fill.

```
--type-tv:        oklch(76% 0.13 224)
--type-movie:     oklch(72% 0.16 250)
--type-anime:     oklch(75% 0.22 350)
--type-manga:     oklch(74% 0.19 305)
--type-game:      oklch(72% 0.17 160)
--type-book:      oklch(81% 0.16 78)
--type-comic:     oklch(75% 0.18 50)
--type-boardgame: oklch(82% 0.20 130)
--type-record:    oklch(72% 0.18 14)
```

### Feedback (toast / banner)

```
--success: var(--status-completed)
--info:    var(--status-in-progress)
--warning: var(--status-paused)
--danger:  var(--status-dropped)
```

### Per-theme overrides

A theme's `themes.css` block becomes 25 lines:

```css
html[data-theme="dracula"] {
  --bg: #181a24;
  --surface-0: #21222c;
  --surface-1: #282a36;
  --surface-2: #313343;
  --surface-3: #44475a;
  --surface-4: #6272a4;
  --border-subtle: rgba(255, 255, 255, 0.05);
  --border: rgba(255, 255, 255, 0.09);
  --border-strong: rgba(255, 255, 255, 0.15);
  --fg: #f8f8f2;
  --fg-muted: #c7c8d1;
  --fg-faint: #6272a4;
  --accent: #bd93f9;
  --accent-strong: #a679f0;
  --accent-hover: #9061e8;
  --accent-soft: rgba(189, 147, 249, 0.16);
  /* status & type tokens inherit unless explicitly overridden */
}
```

That's the entire Dracula theme. No `bg-\[\#...\]` escapes; no per-class
overrides. Existing themes drop from ~25 lines × 7 themes (175 lines)
to ~20 lines × 7 themes (140 lines) with much better fidelity.

## Typography

Roboto Flex (variable) stays — it's a great choice, already loaded,
covers all weight/width axes. Fallback to `system-ui`.

```
--font-sans: "Roboto Flex", system-ui, -apple-system, sans-serif;
--font-mono: ui-monospace, "JetBrains Mono", "Fira Code", Consolas, monospace;
```

### Type scale (Tailwind utility map)

| Token | Size / line-height | Weight | Use |
| --- | --- | --- | --- |
| `display-lg` | 32 / 40 | 700 | Page hero (rare) |
| `display` | 26 / 32 | 600 | Detail page H1 |
| `h1` | 22 / 28 | 600 | Page titles |
| `h2` | 18 / 24 | 600 | Section headings |
| `h3` | 15 / 22 | 600 | Card titles |
| `body` | 14 / 22 | 400 | Default body |
| `body-sm` | 13 / 20 | 400 | Metadata, helper text |
| `caption` | 12 / 16 | 500 | Tag/badge labels, table headers |
| `mono-sm` | 12 / 16 | 500 | Code, ICS URL |

The current app uses `text-3xl` (30 px) for page H1 — slightly too
heavy for a dense info app. `text-2xl` (22 px) at weight 600 is the
target.

### Numerals

Use `font-variation-settings: "opsz" 14;` and `font-feature-settings:
"tnum" 1;` for tabular numerals in tables and stat cards.

## Spacing scale

Tailwind defaults (4 px base) unchanged. Convention:

- Card outer gap: `gap-4` (16 px) at desktop, `gap-3` (12 px) at mobile
- Card padding: `p-4` (16 px) at desktop, `p-3` (12 px) at mobile
- Section spacing: `space-y-8` (32 px) between major sections
- Form row gap: `gap-3` (12 px)
- Inline icon-text gap: `gap-2` (8 px)

A density toggle alters two CSS variables on the root grid template:

```css
[data-density="compact"]    { --grid-min: 140px; --card-pad: 8px; }
[data-density="comfortable"]{ --grid-min: 180px; --card-pad: 12px; }  /* default */
[data-density="cozy"]       { --grid-min: 220px; --card-pad: 16px; }
```

## Radius & elevation

```
--radius-xs: 4px   /* chips, dots */
--radius-sm: 6px   /* buttons, inputs */
--radius-md: 8px   /* cards (default) */
--radius-lg: 12px  /* dialogs, hero card */
--radius-xl: 16px  /* media-card overlay */
--radius-full: 9999px

--shadow-card:    0 1px 2px rgb(0 0 0 / 0.25)
--shadow-elev-1:  0 2px 6px rgb(0 0 0 / 0.30)
--shadow-elev-2:  0 8px 24px rgb(0 0 0 / 0.45)
```

## Iconography

Lucide (already the de facto style of the existing SVGs). Switch to
loading from the lucide package or commit a single sprite. Current 70
SVG files become one `<svg>` sprite + a `{% icon "name" %}` template
tag.

Default stroke width: `1.75 px`. Default size: `20 px` (or `16 px` for
in-button icons).

Status icons:
- Completed: `check-circle`
- In progress: `play-circle`
- Planning: `bookmark`
- Paused: `pause-circle`
- Dropped: `x-circle`

Media-type icons (sidebar):
- TV: `tv`, Movie: `clapperboard`, Anime: `cherry-blossom`,
  Manga: `book-open`, Game: `gamepad-2`, Book: `book`,
  Comic: `book-marked`, Board game: `dice-6`, Record: `disc-3`

## Component library

### Button

```
.btn               /* base: h-9 px-3.5 rounded-md text-sm */
.btn-primary       /* bg-accent-strong text-accent-fg hover:bg-accent-hover */
.btn-secondary     /* bg-surface-2 text-fg hover:bg-surface-3 */
.btn-ghost         /* bg-transparent text-fg-muted hover:bg-surface-2 */
.btn-destructive   /* bg-danger/15 text-danger hover:bg-danger/25 */
.btn-sm            /* h-7 px-2.5 text-xs */
.btn-lg            /* h-11 px-4 text-base */
.btn-icon          /* h-9 w-9 p-0 */
```

States:
- Hover: 1-step darker surface or accent
- Active: scale-[.97] + brightness shift
- Focus-visible: `outline-2 outline-accent outline-offset-2`
- Disabled: `opacity-50 cursor-not-allowed`

### Card

```
.card              /* bg-surface-1 rounded-md border border-border-subtle p-4 */
.card-interactive  /* + hover:bg-surface-2 transition cursor-pointer */
.card-elevated     /* + shadow-card */
.card-flush        /* + p-0 */
```

### Pill / chip

```
.pill              /* inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full
                       text-xs font-medium */
.pill-status       /* bg-{status}-bg text-{status} */
.pill-type         /* border border-current/30 text-{type} */
.pill-meta         /* bg-surface-2 text-fg-muted */
```

### Input

```
.input             /* w-full h-9 px-3 bg-surface-2 rounded-sm border border-border
                      text-fg placeholder:text-fg-faint
                      focus-visible:outline-2 focus-visible:outline-accent */
.input-search      /* + pl-9 (icon slot) */
.textarea          /* same + h-auto p-3 */
.select            /* + appearance-none + chevron icon */
```

### Drawer

Replaces most modals on `≥ md`; bottom-sheet on `< md`.

```
.drawer            /* fixed inset-y-0 right-0 w-full md:w-[480px]
                      bg-surface-0 border-l border-border z-50
                      transform translate-x-full transition-transform
                      data-[state=open]:translate-x-0 */
.drawer-mobile     /* on <md: inset-x-0 bottom-0 top-auto h-[90vh]
                      rounded-t-xl translate-y-full
                      data-[state=open]:translate-y-0 */
```

### Skeleton

```
.skeleton          /* bg-surface-2 rounded-sm animate-pulse */
.skeleton-image    /* aspect-[2/3] bg-surface-2 animate-shimmer */
```

`animate-shimmer` is a 1.5s linear gradient sweep — defined in
`input.css` as `@keyframes shimmer { ... }`.

### Toast

Reuse existing `toast-error`/`toast-success`/etc. but switch the
backgrounds from solid-90% to `--{feedback}-soft` (~16% tint) +
matching border. Lighter, more modern.

### Status sheet

A new compact popover that appears under the primary CTA on the
detail page. Five buttons (Completed / In progress / Planning /
Paused / Dropped), one per row, each a pill in its status color, with
a sixth "Remove from library" destructive row at the bottom.

### Score widget

5 stars-with-halves. Click splits each star into a left and right
half region. Score 0-10 internally, render as 0.0-5.0 with halves.

```
[★★★★½]   8.5/10  → renders as 4.5/5
```

### Status chip on card

Top-left of poster: a circular icon-only chip (24 px) with the status
color as background-tint and the status icon. Hover or tap shows a
tooltip with the status label.

### Progress bar on card

Thin (3 px) colored bar across the bottom of the poster image. Color
matches the status. No bar if status is Planning or Dropped.

## Motion

```
--ease:        cubic-bezier(0.4, 0, 0.2, 1)  /* standard */
--ease-in:     cubic-bezier(0.4, 0, 1, 1)
--ease-out:    cubic-bezier(0, 0, 0.2, 1)
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)  /* used only on sheets */

--duration-fast:   120ms
--duration-base:   180ms
--duration-slow:   280ms
```

Conventions:
- Hover state: `var(--duration-fast) var(--ease)`
- Dropdown / popover open: `var(--duration-base) var(--ease-out)`
- Drawer / sheet open: `var(--duration-slow) var(--ease-spring)`
- Modal backdrop fade: `var(--duration-base) var(--ease)`

Reduced motion:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

## Layout grids

### Page chrome

```
| Sidebar (220 px) | Main (flex-1) |
                   | Top bar (sticky 56 px)  |
                   | Content (max-w-7xl px-6 py-8) |
```

Collapsed sidebar mode: 60 px (icons only).

### Detail page

```
| Hero (full-width, 16:9 capped at 480px tall, gradient fade) |
| Poster (240×360, overlays hero / -mt-24) | Title block + CTA |
| ─ tabs (Overview / Episodes / Cast / Related) ─ |
| Content (single column, max-w-4xl) | Right rail (320px, lg+) |
```

### Media list

```
| Filter bar (sticky, 48 px, single Filter & sort button) |
| Selection bar (slides down when items selected) |
| Grid (auto-fill, minmax(--grid-min, 1fr), gap-3) |
```

### Mobile

```
| Top bar (sticky 48 px: avatar | logo | search | bell) |
| Main (flex-1, px-3 py-4) |
| Bottom nav (sticky 56 px: 5 icons) |
```

## Mock cross-reference

| Token / component | Demonstrated in |
| --- | --- |
| Surface palette | every mock |
| Type scale | `media-details-movie.html`, `statistics.html` |
| Status pills | `home.html`, `media-list-grid.html`, `media-list-table.html` |
| Type accents | sidebar in all mocks |
| Primary CTA + status sheet | `media-details-movie.html`, `track-drawer.html` |
| Half-star score | `media-details-movie.html`, `track-drawer.html` |
| Drawer (desktop) | `track-drawer.html` |
| Bottom sheet (mobile) | `mobile-details.html` |
| Command palette | `command-palette.html` |
| Bottom nav | `mobile-home.html`, `mobile-details.html` |
| Hero + backdrop | `media-details-movie.html`, `media-details-tv.html` |
| 4-up list cover | `lists.html` |
| Wrapped-style stats | `statistics.html` (recap section) |
| Filter & sort popover | `media-list-grid.html` |
| Density toggle | `media-list-grid.html` |
| Theme switcher swatches | `settings.html` |
| Onboarding | `onboarding.html` |
| Notifications bell | top bar of `home.html` |
| Empty states with 2 CTAs | `home-empty.html`, `lists.html` |
| Skeletons | (visual: `home.html` includes a skeleton row at the bottom) |
| Episode list (compact) | `media-details-tv.html` |
