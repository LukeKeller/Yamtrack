# 04 — Redesign plan

Phased rollout, file-by-file scope, and effort estimates for landing
the redesign on top of the current codebase. Each phase is shippable
on its own — the user sees value at every stop.

## TL;DR

Eight phases over four to six weeks of part-time work. Phases 0-2 are
pure plumbing (tokens, components, sidebar) — they unlock everything
that follows but ship with no user-visible regression. Phases 3-7 each
deliver a visible upgrade.

| # | Phase | What ships | Effort |
| --- | --- | --- | --- |
| 0 | Design tokens & Tailwind config | CSS vars, theme rework, no visual change | 0.5d |
| 1 | Component library | Button, Card, Pill, Input partial templates | 1d |
| 2 | Sidebar + top bar + command palette | Collapsible sidebar, ⌘K, theme picker, bell | 2d |
| 3 | Media list + card + status pill | Filter popover, density, status chips | 1.5d |
| 4 | Detail page hero + status sheet | Backdrop, single CTA, half-star scoring | 2d |
| 5 | Home — Up next + activity feed | "Next episode" rail, recent activity rail | 1.5d |
| 6 | Drawers + bottom sheets | Track/Lists/History become drawer/sheet | 1.5d |
| 7 | Mobile bottom nav + onboarding + recap | Bottom nav, post-signup wizard, year-recap | 2d |

Total: ~12 days of focused work; spread over 4-6 calendar weeks given
self-hosted shipping cycle and the YunoHost release cadence
(`CLAUDE.md` calls out the bump-marker flow per release).

## Phase 0 — Design tokens

**Goal.** Lift every hardcoded hex to a CSS custom property. Templates
keep working unchanged because the new tokens initially resolve to the
same hex values.

**Files.**

- `src/static/css/input.css`
  - Add `@theme` block defining custom colors (`bg`, `surface-0..4`,
    `fg`, `fg-muted`, `fg-faint`, `accent`, `accent-strong`,
    `accent-hover`, status × 5, type × 9).
  - Add `:root` block with default-theme values for the same set.
  - Add custom `@keyframes shimmer`.
- `src/static/css/themes.css`
  - Replace each theme block (lines 14-206) with the new pattern:
    20-25 lines per theme, all redefining the same tokens.
- `src/templates/base.html`
  - Update `html` class from `scheme-dark bg-[#212529]` to use
    `bg-[--bg]` or new `bg-app` utility.
  - Add `data-density="{{ user.density|default:'comfortable' }}"` to
    `<html>`.

**Acceptance.**
- All seven existing themes render visually identically to today (use
  a Playwright snapshot per theme to verify).
- `grep -rn "bg-\[#" src/templates` returns zero results.
- New CSS variables are visible in browser DevTools on `<html>`.

**Risk.** Tailwind v4's `@theme` block consumes CSS custom properties
directly — verify the build pipeline still resolves them (the watcher
runs in dev). Mitigate by shipping a pre-built `tailwind.css` to docker
images and validating the static collection runs.

## Phase 1 — Component library

**Goal.** Replace ad-hoc class chains for buttons, cards, pills, and
inputs with reusable Django template fragments. No new look — just
abstraction so phases 2-7 don't multiply the class noise.

**Files.**

- `src/templates/app/components/ui/`
  - `button.html` — `{% include "app/components/ui/button.html" with
    variant="primary" label="Save" icon="save" %}`
  - `card.html` — wraps children with the card surface
  - `pill.html` — `{% include "app/components/ui/pill.html" with
    variant="status" status=media.status %}`
  - `input.html` — generalizes the text input pattern
  - `dropdown.html` — wraps the Alpine dropdown pattern
  - `drawer.html` — drawer/sheet shell
  - `skeleton.html` — variants for card / row / image
- `src/app/templatetags/ui_tags.py` (new)
  - `{% ui_button %}` block tag for the most common case.
  - `{% ui_icon "name" classes="..." %}` — wraps the existing icon
    include so the call site is one tag.
- `src/templates/app/icons/_sprite.svg` (new)
  - Single sprite. Existing individual SVGs stay during transition.

**Migration.** Search-and-replace the top three callsites of each
component (button, card, pill) — there are ~20 per. Leave the rest
alone for now; subsequent phases sweep them.

**Acceptance.** Existing pages render identically. `djlint`/`ruff`
pass.

## Phase 2 — Sidebar + top bar + command palette

**Goal.** Modernize the global chrome. Add a collapsible sidebar, a
⌘K palette, a theme switcher in the top bar, and a notifications bell.

**Files.**

- `src/templates/base.html`
  - Refactor sidebar: 220 px expanded, 60 px collapsed. Toggle button
    at the bottom. Persist state in localStorage and on `User`
    (new field `sidebar_collapsed: BooleanField`).
  - Refactor sidebar nav: group with `<header>` labels (Library,
    Tools, Settings). Each item uses the new `nav_item` component.
  - Top bar: keep search center, add right-hand cluster (theme
    picker, notifications bell, avatar menu).
  - Add a `<dialog id="cmdk">` for the palette, hidden by default.
- `src/templates/app/components/cmdk.html` (new)
  - Renders the palette content via HTMX from `cmdk_view`.
- `src/app/views.py`
  - Add `cmdk_search(request)` view returning HTMX fragments.
- `src/app/templatetags/app_tags.py`
  - `{% nav_item %}` tag (drops the per-item conditional include
    boilerplate).
- `src/static/js/searchShortcut.js`
  - Extend to handle ⌘K → open dialog, `g h/d/l/s` → navigate, `?` →
    open shortcut sheet.
- `src/users/models.py`
  - Add `sidebar_collapsed`, `density`, `notifications_seen_at`.
- `src/users/migrations/00XX_…`
- `src/app/models.py`
  - `UserMessage` already exists; ensure it's queryable for unread
    count (small index).

**Acceptance.**
- ⌘K opens palette anywhere. `Esc` closes.
- Sidebar collapses; layout reflows. Persists across reloads.
- Theme picker in top bar shows swatches, applies live.
- Bell shows unread count (0 if no UserMessages).

**Risk.** ⌘K conflicts with browser default on macOS Safari for
search shortcuts; mitigate by listening on `keydown` with
`preventDefault` when an `input`/`textarea` is not focused.

## Phase 3 — Media list

**Goal.** Tighten the list filter bar and adopt status pills, density
toggle, and a subtle media-type accent.

**Files.**

- `src/templates/app/media_list.html`
  - Replace inline filter row with a single "Filter & sort" button
    that opens a popover.
  - Move grid/table toggle to a small icon-button group.
  - Add density toggle.
  - Wrap with `data-media-type` so the type accent applies.
- `src/templates/app/components/media_card.html`
  - Status chip → top-left circular pill with status-color tint
    background. Tooltip on hover.
  - Score badge → top-right, half-star widget.
  - Progress bar → thin colored line along the bottom of the poster.
  - Hover overlay → kebab opens overflow menu instead of three big
    colored buttons.
- `src/templates/app/components/media_table_items.html`
  - Status column → `pill-status`.
  - Score column → half-star widget.
  - Improve mobile column collapsing (`<td>`s get hidden via media
    queries beyond a width).
- `src/static/css/input.css`
  - `.media-grid` uses the density variable for `--grid-min`.

**Acceptance.**
- Filter bar shrinks to one button + sort + view toggle.
- Status pill color matches across card, table, and detail page.
- Density toggle works without page reload (CSS variable).

## Phase 4 — Detail page

**Goal.** The single highest-impact phase. Add hero/backdrop, collapse
the action cluster, swap the score input, and restructure the page.

**Files.**

- `src/templates/app/media_details.html`
  - Restructure top-of-page into hero composition:
    - Hero `<header>` with backdrop image as background, gradient
      overlay, content (poster on left, title/meta/CTA on right)
      overlapping the bottom edge with `-mt-24`.
    - Fallback: blurred poster as backdrop when no backdrop image.
  - Tabs below hero: Overview / Episodes / Cast / Related (where
    applicable per media type).
  - Single primary CTA showing current status; click opens status
    sheet (status sheet template lives in `app/components/ui/`).
  - Overflow menu (kebab) for Lists / History / Sync / Share /
    Remove.
  - "Repeats" stays as a fold-down but its rows become compact log
    entries.
  - Score is now a half-star widget; click pops the picker.
  - Right rail: streaming providers, details panel, external links.
- `src/app/views.py`
  - Ensure `media.backdrop` is populated; add fallback gradient hash.
- `src/app/providers/tmdb.py` / `igdb.py`
  - Surface `backdrop_path` (already in API, just add to the dict).
- `src/templates/app/components/status_sheet.html` (new)
- `src/templates/app/components/score_widget.html` (new)

**Acceptance.**
- Each media type renders correctly with or without backdrop.
- Primary CTA has visible status; click shows sheet with 5 states +
  remove.
- Score widget renders 5 stars with halves, mapping to the 10-pt
  underlying value.
- All previous functionality preserved (notes, history modal,
  repeats, custom lists).

**Risk.** Highest-effort phase; touches a 910-line template. Mitigate
by splitting `media_details.html` into per-section partials first
(hero, tabs, episodes list, right rail) so each can be reviewed
independently.

## Phase 5 — Home

**Goal.** Reframe the home page around "what should I do next".

**Files.**

- `src/templates/app/home.html`
  - New "Up next" rail (TV/manga/games in-progress, with next-ep CTA).
  - Keep calendar card.
  - Existing In Progress / Planning sections remain but with the new
    card / pill style.
  - New compact "Recent activity" rail under the calendar.
- `src/app/views.py: home`
  - Add `up_next` queryset: in-progress media with a computed
    `next_progress_label` (next episode, next chapter, last save
    delta).
  - Add `recent_activity` queryset: last N `simple_history`
    transitions across all media types for the user.
- `src/templates/app/components/up_next_card.html` (new)
- `src/templates/app/components/activity_item.html` (new)

**Acceptance.**
- New user with no media: home is the empty state (with two CTAs).
- User with TV in progress: "Up next" rail shows next episode for
  each show, with +1 button (HTMX swap).
- Recent activity rail shows last 7 days, click jumps to media.

## Phase 6 — Drawers + bottom sheets

**Goal.** Modernize the modals. Track / Lists / History become
right-side drawers on desktop and bottom sheets on mobile.

**Files.**

- `src/templates/app/components/ui/drawer.html` — implemented in
  Phase 1; wire up here.
- `src/templates/app/components/fill_track.html`
  - Reorganize: top section is "Quick" buttons (Mark watched today,
    +1 progress, Repeat) then "Edit details" reveal.
  - Move primary submit button to a sticky footer.
- `src/templates/app/components/fill_track_episode.html`
  - Same pattern, but simpler (status + watched_at only).
- `src/templates/app/media_details.html`
- `src/templates/app/components/media_card.html`
  - Replace modal container with drawer container.

**Acceptance.**
- Track form opens as a right-side drawer on desktop, bottom sheet on
  mobile.
- Swipe-down on mobile sheet dismisses.
- Quick actions reduce common operations to one click.

## Phase 7 — Mobile bottom nav + onboarding + recap

**Goal.** Polish the mobile experience and add the two new flows.

**Files.**

- `src/templates/base.html`
  - Add bottom nav `<nav>` visible on `< lg`. Hides on scroll-down,
    shows on scroll-up.
- `src/templates/app/onboarding.html` (new)
- `src/users/views.py`
  - `onboarding_view`: 3 steps (pick media types → optional import
    → theme). Sets `user.onboarded = True`.
- `src/users/middleware.py` (new or `app/middleware.py` addition)
  - Redirect new users with `onboarded = False` to `/onboarding/` on
    first visit.
- `src/templates/app/statistics_recap.html` (new)
- `src/app/views.py`
  - `statistics_recap(request, year)`: assembles the wrapped data.
- `src/users/models.py`
  - `onboarded: BooleanField(default=False)` (with data migration to
    set existing users to True).

**Acceptance.**
- New user signup → onboarding wizard → home.
- Mobile bottom nav visible on `< lg`, items match the design.
- `/statistics/recap/2025` renders ten-card narrative.

## Cross-phase concerns

### Accessibility checklist (apply per phase)

- All buttons have `aria-label` or visible text.
- All form inputs have a `<label>`.
- Focus-visible ring on every interactive element.
- Status conveyed by text + color, not color alone.
- Color contrast ≥ 4.5:1 for body text on every theme (lighthouse
  audit per phase).
- Reduced-motion respected.

### Performance budget

- Initial HTML: < 80 KB gzipped per page (currently ~50 KB).
- JS: drop jQuery + Select2 (save ~150 KB). Replace Select2 with
  TomSelect (~30 KB). Net savings ~120 KB.
- Images: backdrop heroes use TMDB's `w1280` variant — ~150 KB each.
  Lazy-load below the fold. `<img loading="lazy">` everywhere except
  the hero.
- CSS: Tailwind v4 build output should stay < 60 KB gzipped.

### Migration safety

- Each phase is a single PR (or feature branch) that ships
  end-to-end.
- New `User` fields (`sidebar_collapsed`, `density`, `onboarded`,
  `notifications_seen_at`) ship with sensible defaults.
- No template that exists today gets *deleted* — they get
  refactored. URL patterns don't change.
- Per `CLAUDE.md`'s fork-package shipping flow, each phase that
  changes user-facing surfaces gets a bump-marker commit on `main`
  and a corresponding `yamtrack_ynh` bump.

### Theming validation

The new token system has to render correctly under every existing
theme. Playwright tests per theme:

```python
@pytest.mark.parametrize("theme", ["default", "dracula", "catppuccin-mocha",
                                    "catppuccin-macchiato", "catppuccin-frappe",
                                    "nord", "gruvbox-dark", "tokyo-night"])
def test_home_renders_under_theme(live_server, page, user, theme):
    user.theme = theme
    user.save()
    page.goto(live_server.url + "/")
    expect(page.locator("h1")).to_be_visible()
    # snapshot per theme for visual regression
    page.screenshot(path=f"tests/snapshots/home-{theme}.png")
```

CI runs `playwright install` already (per `CLAUDE.md`), so this is
additive.

### Backout plan

Each phase ships behind a soft toggle (just the feature branch). If
the live demo (yamtrack.fuzzygrim.com isn't this fork's, but the
homelab deployment is) reports a regression:

1. Revert the merge commit on `main`.
2. Bump `yamtrack_ynh` to the prior commit.
3. The next deploy reverts.

The token rewrite (Phase 0) is the riskiest — it's a global CSS
change. If themes render wrong, the rollback is one revert.

## Out of scope (explicitly)

These would be improvements but aren't part of this redesign:

- React/Vue rewrite. The HTMX + Alpine + Django stack stays.
- Recommendation engine.
- Social features (follows, comments, public profiles).
- Push notifications. Apprise covers the need.
- A separate native iOS/Android app. The PWA is the mobile story.
- Migration to PostgreSQL by default. SQLite stays the default.
- Theming engine extensibility (user-uploaded themes). Theming stays
  curated to maintain quality.

## Definition of done

The redesign is done when:

1. All 8 phases have shipped to `main`.
2. The README screenshots are updated.
3. The seven themes render correctly under Playwright snapshots.
4. `grep -rn "bg-\[#" src/templates` returns zero results.
5. A new user can: sign up → onboard → import from Trakt → see "Up
   next" → mark an episode watched → see year-recap, in under 90
   seconds.
6. The mobile install (PWA) shows bottom nav on iOS Safari, Chrome
   Android, and Firefox Android.
7. Lighthouse accessibility score ≥ 95 on home and detail pages
   (currently around 85).

Once complete, the upstream PR back to FuzzyGrim/Yamtrack becomes a
viable proposal — the rewrites are all template-local, behavior is
preserved, and the patterns are demonstrably aligned with modern
trackers in the same niche.
