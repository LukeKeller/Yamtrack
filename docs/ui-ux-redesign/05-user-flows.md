# 05 — Key user flows

The seven flows the redesign optimizes for, with before/after counts.

## Flow 1 — First-time user: sign up to first track

**Today (10 clicks).** Sign up → land on empty home → notice sidebar →
click TV → empty state → click "Browse TV" → land on TMDB-discovery
list → click a show → click "Add to tracker" → fill form → save.

**After (4 clicks).**

```
sign up
  ↓
onboarding step 1 (pick media types you track)
  ↓
onboarding step 2 (optional: connect Trakt/Plex/MAL — skip OK)
  ↓
onboarding step 3 (theme picker, skip OK)
  ↓
home with empty-state CTA: "Add your first movie"
  ↓
⌘K / search dropdown / direct link to search
  ↓
type "dune"
  ↓
hit Enter → quick-add (mark watched today) OR click for detail page
  ↓
done
```

Quick-add via search dropdown drops "click → detail page → fill form
→ save" to "press w" (status sheet w shortcut). Power-user case: ⌘K +
type + enter + w + enter = under 4 seconds.

## Flow 2 — Returning user: "what's next tonight?"

**Today.** Open app → land on home → scroll to "In progress" → find
the show → click → click season → find the next unwatched episode →
click track button → fill modal → save.

**After.** Open app → home shows "Up next" rail with next episode of
each in-progress show → click +1 on the episode card.

Three clicks down from seven, and the new pattern matches what Trakt
users already expect.

## Flow 3 — Power user: search and act

**Today.** Click search → type → hit Enter → wait for results page →
click card → wait for detail page → click track → fill modal → save.

**After.** Press ⌘K → type query → results inline → press `w` (or
`p` / `c`) to set status on the highlighted result without leaving
the current page.

The current page (whatever the user was looking at) doesn't reload.

## Flow 4 — Mobile user: mark an episode watched on the bus

**Today.** Open PWA → hamburger to find TV → tap → find the show →
tap → wait for detail page (heavy) → scroll to episode → tap edit
icon → modal centered with full form → tap status → tap save.

**After.** Open PWA → bottom nav "Home" → "Up next" carousel at top →
swipe to find the show → tap +1 button → bottom sheet rises with
quick actions ("Mark E5 watched today", "Skip ahead", "Edit details")
→ tap first → sheet dismisses with confirmation toast.

Three taps vs seven; touch targets ≥ 44 px; one-handed reachable.

## Flow 5 — Importer: bring my Trakt library over

**Today.** Settings → Import Data → scroll to Trakt → check
"Import private profile" → click "Connect with Trakt & Import" → OAuth
dance → land back at import page with a green "Started" badge → wait
→ refresh to see history.

**After.** Same OAuth dance (no way around it) but:

- Onboarding step 2 surfaces the same OAuth path → first-time users
  hit it inline.
- After the OAuth callback, a persistent top-of-screen banner shows
  "Importing from Trakt — 142/280 …" with a progress bar.
- The banner navigates the user to import history on click.
- Toast notification appears on completion ("Trakt import finished —
  280 movies, 142 shows added").

Eliminates the "did anything happen?" gap.

## Flow 6 — Stat-curious: see this year's recap

**Today.** Settings → not in settings → click Statistics → date range
to "This year" → scroll through 6 chart panels.

**After.** Statistics → "See your 2025 recap" CTA at the top → opens
a swipeable 10-card narrative ("you watched 142 movies", "your
average score was 7.3", "your favorite genre was horror", "your
longest streak was 23 days"…).

Same data, story-shaped. Shareable image export for power users.

## Flow 7 — Self-hoster: change the theme

**Today.** Settings → Preferences → scroll to "Theme" select → choose
→ submit → reload page to see effect.

**After.** Top bar → theme picker icon → popover with 8 color
swatches → click → applies immediately (CSS variable swap). Persists
automatically.

Zero page reload. Useful when a user wants to A/B their themes.

## Flow 8 — Recover: I marked something wrong

**Today.** Find the item → click track button → modal opens with all
fields → realize you don't see "Undo" → cancel → search for history
modal somewhere → find item history → re-edit fields manually.

**After.** Toast after every mutation reads "Marked X as completed.
[Undo]". One-click revert for 8 seconds.

Plus: the detail-page history modal stays as the comprehensive log
view.

## Anti-flows (intentionally NOT optimizing)

- **Browse-as-discovery.** Browse is a power user feature, not a
  primary surface. Keep it 1-2 clicks deep but don't push it on
  every visit.
- **Per-episode score input.** Letterboxd doesn't score episodes, and
  the data model permits it but the cost is high. Keep it as a
  power-user form, not a flow.
- **Cross-user social.** No "follow", no "@-mentions". Lists with
  collaborators is the social ceiling.
