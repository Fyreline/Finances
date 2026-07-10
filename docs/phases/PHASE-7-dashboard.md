# Phase 7 — Dashboard & visual polish (owner: **Fable**)

Every feature exists by now; this phase makes the bubble home screen feel like one
designed object rather than six phases' worth of parts. DESIGN.md is the contract —
especially §3 (the bubble pattern, which is the app's signature: **product direction
2026-07-10, bubbles ARE the navigation**), §2c (chart craft), and §6 (money without
guilt).

## Scope
1. **Bubble roster sweep** (DESIGN §3b): every bubble matches its collapsed content
   spec exactly — hero figure sizes, pill placement, sparkline dimensions, setup
   states; roster reflects the accepted/rejected suggestions; order/spans right at all
   three breakpoints; hover/press physics per §3a.
2. **Expand transitions** (§3c): brace connector tuned (peak spring tracking,
   panel-outline merge, no clipping), sheet physics on mobile (drag-handle,
   swipe-dismiss velocity), chart draw-ins mount after settle, reduced-motion
   variants, focus choreography.
3. **Chart-craft audit** (§2c): both themes through a contrast checker for every
   line/text token; deuteranopia simulation walk; pale-token outline rule; every
   chart states its window/as-of date; bars start at zero; `SpendCalendar` built here
   if time allows (it's the one nice-to-have).
4. **Copy pass** (§6): every empty state, verdict, tip, and error in one sitting —
   British English, serif warmth where specified, no guilt, no exclamation marks.
   The tax disclaimer blocks and deals date-stamps verified present.
5. **KakeiMark**: a small wordmark glyph in the household tradition (CatMark,
   MichiMark) — suggestion: a hanko-style seal square containing 家, `currentColor`
   so it follows clay and theme; flat export for favicon/PWA icons like the siblings.
6. Performance: home renders <100ms on cached data (bubbles read one aggregate
   endpoint... if that's not true by now, add `GET /api/summary/bubbles` returning
   every bubble's glance payload in one call — the collapsed home should be ONE
   fetch); charts are static SVG, no rAF loops at rest.

## Acceptance
- [ ] DESIGN.md §7 checklist — every box (it is this phase's real acceptance list).
- [ ] One-fetch home: network tab shows a single summary call on load (post-auth).
- [ ] Side-by-side with Michi/Mishka: same paper, same ink, same calm — a household
      member should recognise the family instantly (subjective, human-checked).
- [ ] Screenshots (light + dark, mobile + desktop, collapsed + one expanded bubble)
      attached to the phase report.
