# Kakeibo — Design System

Purpose: the visual + interaction contract for the Kakeibo web app. Direction: **the
household's Aizome woodblock language, applied to a ledger** — calm washi paper, indigo
ink, hanko-crimson accent, hairline borders not shadows, and numbers treated with the
respect of a hand-kept 家計簿: mono, tabular, honest. Mishka Hub is a poster wall and
Michi is a journey; Kakeibo is **a desk** — dense in data, quiet in chrome, nothing
animated that doesn't carry information.

Inherits wholesale from
[`MishkaHub/docs/DESIGN.md`](/Users/mack/Documents/Dev/MishkaHub/docs/DESIGN.md)
(Anthropic-editorial tokens: type stack, spacing scale `4/8/12/16/24/32/40/48/64/96`,
radii `4/8/16`, borders-not-shadows, component specs) and the shared **Aizome palette**
(`theme.css` — canonical copy in
`learningLanguageMachine/apps/web/src/theme.css`, mirrored here by
`learningLanguageMachine/scripts/sync-theme.sh`; **add
`DST_KAKEIBO="/Users/mack/Documents/Dev/Finances/apps/web/src/theme.css"` to that
script in Phase 1** — values-only edits happen in the canonical copy, never in the
mirror). This doc specifies only the Kakeibo delta: the data-viz extension and the
finance component library.

## 1. Inherited, restated in one breath

Type: Schibsted Grotesk (display) / Inter (body) / JetBrains Mono (numbers, always) /
Source Serif 4 (rare editorial accent — the empty-state line, the tax disclaimer's
opening). Semantic colour tokens only (`bg-paper`, `text-ink`, `border-line`,
`text-clay` …) — a hex in a component is a review-blocker; dark mode via the `.dark`
class variant, ThemeToggle port, storage key `kakeibo-theme`. British English, calm
tone, sentence case, no exclamation marks. Motion via `motion`, gated on
`useReducedMotion()`; on this app motion is scarce by design — count-up on the
safe-to-spend number, progress-bar fill on load, and that's nearly it.

## 2. Data-viz extension (the Kakeibo delta)

The shared palette reserves a 4-step viz ramp (`--color-viz-1..4`). A finance dashboard
needs more: 8 categorical slots, a sequential ramp, a diverging pair, and semantic
money colours. These are **Kakeibo-only tokens** living in `apps/web/src/index.css`
(Michi precedent: app-specific tokens stay out of the shared `theme.css`; promote to
canonical only if a sibling ever wants them). `--color-viz-1..4` keep their shared
values; 5–8 extend the family.

### 2a. Tokens (drop into `index.css` `@theme`)

```css
@theme {
  /* categorical — light mode (on #f7fbfa paper). Order interleaves hue AND lightness
     so adjacent slots differ for colour-blind users; do not reorder. */
  --color-viz-5: #37718e;   /* steel blue    (aizome sky, exact chosen hex) */
  --color-viz-6: #c33c54;   /* hanko crimson (clay) */
  --color-viz-7: #2e8b74;   /* mint teal     (olive family) */
  --color-viz-8: #9c3f6d;   /* plum          (fig) */
  /* viz-1..4 from theme.css: #8ee3ef pale cyan · #aef3e7 pale mint ·
     #f2c7cf sakura pink · #e8dfc0 sand — pale: FILLS ONLY, never lines/text (§2c) */

  /* semantic money */
  --color-gain: #2e8b74;        /* income, growth, under-budget  (= olive) */
  --color-spend: #17293a;       /* ordinary outgoings are INK, not red — spending is
                                   normal life, not an error (§6) */
  --color-over: #c33c54;        /* over target/budget — crimson as information */
  --color-setaside: #37718e;    /* committed/reserved money (tax set-aside, goals) */

  /* sequential ramp (heat/intensity, e.g. spending calendar) — mint→indigo, 5 steps */
  --color-seq-1: #e9f6f2; --color-seq-2: #aee3d8; --color-seq-3: #6aaebc;
  --color-seq-4: #37718e; --color-seq-5: #254e70;

  /* diverging (under ↔ over, projection vs target): teal ← paper-neutral → crimson */
  --color-div-neg: #2e8b74; --color-div-mid: #dcebe8; --color-div-pos: #c33c54;
}
.dark {
  --color-viz-5: #7fb3d0; --color-viz-6: #e05a72; --color-viz-7: #5fcfae; --color-viz-8: #d1729c;
  --color-gain: #5fcfae; --color-spend: #ecf6f4; --color-over: #e05a72; --color-setaside: #8ee3ef;
  --color-seq-1: #16283a; --color-seq-2: #1f4254; --color-seq-3: #2f6b7e;
  --color-seq-4: #5aa7bd; --color-seq-5: #8ee3ef;
  --color-div-neg: #5fcfae; --color-div-mid: #223c4e; --color-div-pos: #e05a72;
}
```

### 2b. Stable category → colour assignment

Colour identifies a category *forever*, across every chart and both themes —
`categories.viz_slot` (DATA_MODEL.md §3) pins it:

| slot | token | category |
|---|---|---|
| 1 | viz-5 steel blue | housing & bills (the big fixed block) |
| 2 | viz-6 crimson | groceries |
| 3 | viz-7 teal | eating out |
| 4 | viz-8 plum | fun & subscriptions |
| 5 | viz-1 pale cyan | transport |
| 6 | viz-3 sakura | shopping & gifts |
| 7 | viz-4 sand | holidays |
| 8 | viz-2 pale mint | everything else |

Slots 5–8 (pale) go to categories that are typically smaller — pale fills read fine at
small area, and their ink outlines (§2c) keep them legible. Income series always
`gain`; rental series always `setaside`; never reuse a category colour for a
non-category series.

### 2c. Chart-craft rules (apply to every chart, no exceptions)

1. **Contrast:** pale tokens (viz-1..4, seq-1..2) are fill-only, always with a 1px
   `line-strong` outline; lines/text/icons use only tokens with ≥3:1 contrast on
   `paper` (viz-5..8, ink family, gain/over). Verify both themes at Phase 7 with a
   contrast checker — acceptance item.
2. **Never colour alone:** every series/segment gets a direct label or an adjacent
   legend chip with text; over/under states pair colour with sign and words ("£62
   over"). Colour-blind check (deuteranopia sim) is a Phase-7 acceptance item.
3. **Direct labelling over legends** where space allows: category bars carry their
   label + amount on the bar row itself; sparklines label first/last values only.
4. **Numbers:** JetBrains Mono, `tabular-nums`, `£1,234.56`; axis ticks 11px mono
   `ink-soft`; no gridline heavier than `line`; zero-line `line-strong`.
5. **No 3D, no pie for >4 slices** (the one donut, §5e, shows exactly
   spent/committed/set-aside/remaining), no dual y-axes, no truncated bar axes —
   bars start at zero, always. Trend lines may zoom the y-domain but then show a
   dotted zero/target reference.
6. **Every chart states its window** ("last 6 months", "since 1 Jul 2026") and, for
   anything benchmark- or deals-derived, its as-of date (API.md §4/§6b).

## 3. The bubble home screen — Kakeibo's primary navigation

**Product direction (from the user, 2026-07-10): the home screen is a set of
"bubbles"** — compact rounded overview tiles, one per goal/domain, each glanceable in
a second; tapping a bubble expands it into that domain's full detail view (charts,
tables, actions). Bubbles are not widgets on a bigger page — **they are the app's
navigation**. There is no tab bar; the header is minimal (wordmark **Kakeibo** +
家計簿 in `ink-soft` 12px; sync-status pill, `kraft`-warn when >24h; ThemeToggle) and
everything else is bubble → detail → back.

### 3a. Bubble form: rounded-square cards, not circles

Bubbles are `bg-paper-mid border border-line rounded-lg` (the shared 16px radius)
cards with generous padding (`p-5`) — **not** literal circles or pills. Justification
against the existing tokens: the Aizome/Anthropic language is editorial — hairline
borders, paper surfaces, radii capped at 16px, "nothing pill-shaped except actual
pills" (Mishka DESIGN §1c). Circles also fight the content: every bubble's payload is
a left-aligned mono number plus a mini-chart, which wants a rectangle. The "bubble"
quality comes from behaviour and rhythm instead: uniform rounded cards in a loose
grid, hover lift (`border-line-strong` + translate-y −1px, Mishka card spec), a
gentle press-scale 0.98 on tap, and the expand transition (§3c). One token addition
for the softness: bubbles may use `rounded-lg` with padding tuned so the corner radius
reads plump at small sizes; do **not** invent a new radius token.

### 3b. The grid and the bubble roster

Container `max-w-72rem`; CSS grid, gap 16px: 1 column <640px, 2 columns <1024px,
3 columns ≥1024px. Safe-to-spend is the hero bubble and always spans the full row.
**This is the canonical bubble list — the human sanity-checks the grouping here:**

| # | Bubble | Goal(s) | Collapsed: what you see in one glance | Expands into |
|---|---|---|---|---|
| 1 | **Safe to spend** (hero, span-all) | 1 | `£487.20` (38px mono) + `£32/day · 15 days left` + the waterfall strip (§4a) rendered small (8px tall, unlabelled) | full waterfall with labelled segments + every formula line from API.md §6a + settings for payday/income/buffer |
| 2 | **House deposit** | 2 | progress bar to the configured target (example figures only: `£1,240 · 6%`), verdict pill (`on track`/`behind`), target tick (mono date label, e.g. `10 JAN 2027`) — real target/deadline load from local config, never hardcoded (PRIVATE.md) | GoalBar detail (§4c): projection marker, trend, catch-up sentence, pledge editor, contribution series chart |
| 3 | **T212 rebuild** | 3 | current balance (example: `£412`) + 6-month sparkline + change-since-baseline line | rebuild trend chart (§4c variant), baseline annotation, snapshot history table |
| 4 | **Spending this month** | 5 + 6 | month total `£1,204` + top-3 category chips with amounts + worst verdict pill (e.g. `eating out · above average`) + `3 tips` count chip | detail view with internal tabs: **Breakdown** (§4d) / **Transactions** (§4e) / **Tips** (tip cards with dismiss) |
| 5 | **Recurring** | 7 | `£214.50/mo committed` + `2 worth a look` (`oat` pill) + next-due line `Netflix · 3 Aug` | RecurringList (§4f) with verdict actions |
| 6 | **Tax year 2026-27** | 8 | profit-so-far `£2,340` + `est. tax £491` (or `estimate needs 3 inputs` pill) + unreviewed-docs count; hosts the SA-deadline callout when live | TaxPage (§4g): Documents / Ledger / Estimate tabs |
| 7 | **Savings deals** | 4 | best researched rate `4.60% AER · Coventry BS` + `checked 13 Jul` date (always) | DealsPage (§4h) |
| 8 | **Net worth** (S1 accepted, Phase 9) | 9 | total `£24,830` + 90-day sparkline + one dot per account | TrendLine + account breakdown list, **plus S2 (emergency fund) and S4 (contractor gap) folded in as two quiet sections** — see §3e below for why they live here rather than as their own bubbles |
| 9 | **Wants & gifts** (goals 10-11, Phase 9) | 10, 11 | item count on the wants list + how many currently `fits now` + occasion count (any `over limit` flagged as calm information) | Internal tabs **Wants** / **Gifts** (same pattern as the Spending bubble's tabs) — an add-item form, an affordability pill per want item, and per-occasion cards with their own items + running total against the limit |
| 10 | **Splits** (if S3 accepted) | 9 | `Partner owes £23.40` / `even` + last entry line (real display name from config, PRIVATE.md) | Warikan ledger + settle action |

### 3e. Where S2 and S4 landed, and why (Phase 9)

PHASE-9-personal-goals.md left the emergency-fund check (S2) and the contractor-gap card
(S4) to implementer judgement between "their own small bubble" and "a line inside an
existing detail view." Both landed inside the **Net Worth** bubble's detail view, not as
new bubbles:

- S2 (emergency fund) needs exactly the same accessible-cash figure Net Worth's account
  breakdown already computes (current + savings accounts, excluding investments) — no new
  data source, and PLAN.md §4 S2's own text calls it "a quiet dashboard card," not a
  bubble in its own right.
- S4 (contractor gap) is explicitly "a quiet card" per PLAN.md §4 S4's own wording; its
  `fte_runway` goal, once a conversion date is set, reads through the ordinary goals
  endpoints rather than inventing a new one, and pairs naturally with a screen that's
  already about "the money you have."
- Adding two more bubbles (10 total, after goals 10-11's "Wants & gifts" bubble) would
  have pushed past what §3d calls "one hero figure plus at most three supporting
  elements" territory for the home *screen* as a whole, not just one card — DESIGN.md's
  own density principle extends naturally from "inside a bubble" to "how many bubbles."

Detail views are allowed to go dense (§3d: "the desk opens its drawers"), so Net Worth's
detail is now three stacked sections — trend chart + breakdown, emergency fund, contractor
gap — each with its own `border-t` divider and mono section label, never crowding the
collapsed glance (which still shows only the total + sparkline + account dots).

Bubble order is user-arrangeable later (`settings_json.dashboard_tiles_order`); the
default is the table order. A bubble whose integration is `not_configured` collapses
to its setup state (serif one-liner + one button, §6) — it never shows fake numbers.

### 3c. Click-to-expand interaction

Consistent with the household's two existing patterns — Mishka Hub's in-place
expansion panel (poster → detail panel + brace connector) and its detail drawer
(bottom sheet on mobile):

- **Desktop (≥1024px): in-place expand.** Tapping a bubble expands a full-width
  detail panel directly **below the bubble's grid row** (the grid rows below shift
  down); the bubble stays visible and highlighted (`border-liquid`), joined to the
  panel by the **BraceConnector** pattern ported from Mishka Hub's `App.tsx`
  (`bracePath(peakPercent)` — peak slides on `useSpring` to the active bubble; panel
  outline `border-liquid` on sides+bottom, no top border, so brace and panel read as
  one shape; remember the `overflow: visible` gotcha, Mishka DESIGN §7). **Phase 10**
  moved this from a bare stroked brace to Mishka Hub's actual liquid-glass treatment
  (`--color-liquid`, "Mishka's connector surface" — already in the shared theme.css):
  the brace stroke itself is `var(--color-liquid)`, plus a soft liquid-tinted
  gradient fill pooling under the curve (a filled glass surface, not just an outline)
  — subtler than Mishka's full poster halo ("a desk, not a poster wall"), but the
  same connected-surface idea, and the bubble/panel borders switched from
  `border-clay/60` to `border-liquid` to match. Tapping the bubble again, `Esc`, or
  tapping another bubble closes/moves it. One panel open at a time.
- **Mobile (<1024px): full-height bottom sheet** (`bg-paper rounded-t-lg
  shadow-float`, backdrop `ink/30`, no blur — Mishka drawer spec), slides up 260ms
  ease-out, drag-handle + swipe-down or back-gesture to dismiss. The sheet header
  repeats the bubble's glance line so context carries over.
- **Deep-linking:** each expanded state sets a hash (`#deposit`, `#spending/tips`) so
  reload/back restore it; internal tabs (Spending, Tax) are hash segments.
- Expansion animates height/opacity only (no layout thrash on the charts — charts
  mount after the panel settles, then run their ≤600ms draw-in). Reduced motion:
  instant open, no brace slide, no chart draw-in.
- Keyboard: bubbles are `<button>`s in DOM order; expanded panel is `aria-expanded` +
  `role="region"` labelled by the bubble; focus moves into the panel on open, returns
  on close.

### 3d. Density inside bubbles

A bubble is allowed **one hero figure** (24–38px mono) plus at most three supporting
elements (pill, sparkline, sub-line). If a bubble wants a fourth, that content belongs
in its detail view. Detail views may go dense (tables, full charts) — the desk opens
its drawers.

## 4. Component specs — the finance library

These components live **inside the expanded detail views** (§3c); several also render
a compact "glance" variant inside their collapsed bubble, noted per component.

### 4a. Safe-to-spend hero (bubble #1)

The hero bubble (collapsed spec in §3b) and its expanded panel:

- Left: label `SAFE TO SPEND · 12 JUL – 27 JUL` (mono 11px tracked `ink-soft`), the
  figure `£487.20` (38px mono, `ink`; `over` crimson only when negative), sub-line
  `£32/day for the next 15 days` (13px `ink-soft`).
- Right: the **waterfall strip** — one horizontal stacked bar (height 12px, rounded-sm)
  of the whole month's income: segments committed (`viz-5`), goals (`setaside`), tax
  set-aside (`setaside` at 60% opacity, hatched via SVG pattern), buffer (`oat`),
  spent-so-far (`ink` at 30%), remaining (`gain`). Each segment ≥12px wide gets an
  inline label; the rest listed in a mono legend row beneath. This is goal 1's formula
  (API.md §6a) made visible — every deduction inspectable, nothing mysterious.
- Setup-missing state: serif line "Tell Kakeibo about payday and take-home pay to
  unlock this." + a single secondary button → settings. Never fake numbers.

### 4b. StatTile

`bg-paper-mid border-line rounded-lg p-4`: mono 11px label, 24px mono value, optional
delta chip (`↑ £41 vs Jun` — `gain`/`over` by *meaning*, e.g. spending up = neutral ink
unless over benchmark), optional 48×16 sparkline right-aligned (§5a).

### 4c. GoalBar (goals 2 & 3)

- Header row: label + verdict pill (`on track` = `bg-olive/15 text-olive`; `behind` =
  `bg-kraft/20 text-clay-deep` — kraft, not crimson: behind on a goal is a nudge, not
  a failure; `no trend yet` = `bg-oat text-ink-mid`).
- The bar: 12px track `paper-deep`, fill `setaside` with rounded cap; a **target tick**
  (2px `ink` notch + mono date label, real value from config beneath) and a
  **projection marker** (hollow circle at `projected_at_target`, `gain` if ≥ target
  else `over`).
- Sub-rows (13px mono, example figures only — real values load from config):
  `£1,240 of £10,000 · £X/mo needed · trend £Y/mo` — and when behind, the exact
  catch-up sentence from the API: *"behind — £X/month from now reaches it"*.
- T212 rebuild variant: no target bar, instead a 6-month **contribution trend**
  mini-chart (§5b) with a baseline annotation (real baseline amount/date from config)
  and the honest series label "balance growth" (market movement included —
  DATA_MODEL.md §4).

### 4d. Category breakdown (goal 5)

Horizontal bars, not a pie: one row per category, ordered by spend. Row = 20px colour
chip (slot colour) + label + `£412.33` right-aligned mono + bar (share of month, max
60% row width) + verdict pill when a benchmark exists (`maintainable` olive /
`average` oat / `above average` kraft — wording exactly these, and the pill's tooltip
carries the band bounds + "rough ONS-derived band, <as-of date>" per API.md §6b).
Clicking a row filters the transaction table beneath. A serif footnote under the chart:
the methodology note, always visible, 12px `ink-soft`.

### 4e. TransactionTable

Desktop table / mobile card-rows. Columns: date (mono 11px), counterparty (+ reference
in `ink-soft` beneath), category chip (click → recategorise popover listing categories
with their colour chips; writes PATCH, marks row `manual` with a tiny ⌁ badge),
amount right-aligned mono (income prefixed `+` in `gain`; spending plain ink — §6).
Row height 44px; hairline row dividers `line`; sticky month headers; unsettled rows at
40% opacity with a `pending` pill. Rental-flag toggle in the row's overflow menu
(feeds TAX). 50/page, mono pagination.

### 4f. RecurringList (goal 7)

Rows: cadence glyph (↻ monthly, etc.), label, mono amount + `≈ £9.99/mo` equivalent for
non-monthly, `next expected 3 Aug`, tenure (`since Mar 2026 · 5 payments`),
confidence dots (3 filled = high), and flags: `price rise` kraft pill (old→new in
tooltip), **cancel-candidate** = `bg-oat` pill reading `still using this?` — with
keep / cancel-candidate / cancelled actions. Footer stat: `£214.50/month committed`.
Copy never asserts non-usage (DATA_MODEL.md §3a.4).

### 4g. Tax card + TaxPage (goal 8)

- Dashboard card: current tax year, `profit so far £X` (mono), `estimated tax £Y` or —
  while inputs are missing — `estimate needs 3 inputs` as a quiet `oat` pill linking to
  the config form. If `sa_registration_deadline` tip is live, it renders here too, and
  this is the one place allowed a crimson-bordered callout (a statutory deadline is
  the exception to §6).
- TaxPage: three stacks — **Documents** (unreviewed first, doc-type select + amount
  field + reviewed toggle per row), **Ledger** (SA105-shaped table grouped by expense
  type, add-entry form), **Estimate** (the two-method comparison as two side-by-side
  cards, expenses+S24-credit vs £1,000 allowance, winner outlined `border-olive`, each
  line of the computation visible mono — the estimate must be *auditable by eye*,
  TAX.md §5).
- **The disclaimer block** (every tax surface, non-dismissable): `bg-oat rounded-md
  p-3`, serif first sentence — "Kakeibo estimates for planning; it is not tax advice."
  — then 12px: "Numbers here must be checked against HMRC's own calculators or an
  accountant before filing." Styled warmly, worded absolutely.

### 4h. DealsPage (goal 4)

Cards per deal: provider + product (display), `4.60% AER` (24px mono), access/FSCS/ISA
chips, `notes` line, and — mandatory — source link + `checked 13 Jul 2026` in mono
11px. Stale run (>35 days) banners the page in `oat`: "These rates were researched on
<date> and may have changed." A `your £X here ≈ £Y/year` line personalises against the
current T212/savings balance (simple AER × balance, labelled "rough").

## 5. Chart primitives (`src/charts/` — hand-rolled SVG, no library)

| Component | Spec |
|---|---|
| **Sparkline** | 48–120×16–24px, 1.5px path `viz-5` (or semantic token by series), no axes, dot on last point, first/last labels optional. Nulls break the line, never interpolate. |
| **TrendLine** | goal/net-worth series: x time, y £; area fill token at 12% opacity under a 2px line; dotted target line + tick; hover (pointer) / tap (touch) → vertical rule + mono tooltip `1 Sep · £4,120`. |
| **CategoryBars** | §4d — plain divs, actually; only the waterfall/donut/lines are SVG. |
| **WaterfallStrip** | §4a — stacked `<rect>`s, SVG pattern for the hatched segment, 200ms width transition on load (reduced-motion: none). |
| **Donut** | one use (month overview): 4 segments max (§2c.5), 28px, centre = remaining figure. |
| **SpendCalendar** | (Phase 7, nice-to-have) month grid, cells shaded seq-1..5 by daily spend; weekday labels; a legend showing the 5 steps with £ bounds. |

All primitives take pre-shaped `{label, value_minor, token}` arrays — shaping happens
in testable functions (`charts/shape.ts`), rendering is dumb. Axis/format helpers from
`money.ts` only.

## 6. Voice — money without guilt

The CLAUDE.md house rule ("no red-alert guilt UI") matters most in a finance app:

- Spending is printed in **ink**, not red. Crimson (`over`) appears only for genuine
  threshold crossings (negative safe-to-spend, over-benchmark verdicts get *kraft*
  first, crimson only when >1.5× band) and the SA-deadline callout.
- Verdict language: "above average" not "overspending"; "worth a look" not "warning";
  "behind — £X/month reaches it" not "you've missed your target".
- Empty/setup states are serif and warm: "Nothing synced yet — connect Starling to
  begin." The app never nags twice about the same thing in one view.
- Numbers are never animated to look bigger/smaller than they are; count-ups run
  ≤600ms and land exactly.

## 7. Acceptance criteria (Phase 7 verifies)

- [ ] `theme.css` is byte-identical to the canonical Michi copy (sync script extended,
      run, diff clean); every colour in the app resolves to a semantic or §2a token —
      no raw hex in components (`grep -rn "#[0-9a-fA-F]\{3,6\}" src/components src/charts`
      returns nothing).
- [ ] Both themes: §2c.1 contrast checks pass for all line/text tokens; deuteranopia
      simulation keeps every chart readable (labels carry the meaning).
- [ ] Safe-to-spend waterfall segments sum exactly to income (pence-perfect) and each
      is inspectable (label or legend).
- [ ] Goal bar shows the real, locally-configured goal's computed required-per-month
      figure correctly on first render, ceiled to the pound per ARCHITECTURE.md §6
      (DATA_MODEL.md §4a) — verify live against local config, never assert the real
      number in a committed doc.
- [ ] All money everywhere is mono + tabular-nums; spending renders in ink, not red;
      the only crimson on a default dashboard is the wordmark accent (and a genuine
      threshold state if one exists).
- [ ] Tax surfaces all carry the §4g disclaimer block; deals all carry source + date.
- [ ] The home screen is the §3b bubble roster (correct roster for the accepted
      suggestions), each bubble matching its collapsed content spec; no tab bar.
- [ ] Desktop: bubble → in-place panel with brace connector (peak tracks the active
      bubble; no clipping); mobile: bottom sheet with swipe-dismiss; `#hash`
      deep-links restore expanded state and internal tab on reload.
- [ ] Keyboard walkthrough: bubbles focusable/openable, focus enters and returns on
      panel open/close; recategorise, verdict actions, goal edit all reachable; focus
      rings per Mishka spec. `prefers-reduced-motion` → instant expand, no count-up,
      no bar-fill or brace transitions.
- [ ] Lighthouse a11y ≥ 95 on the home (bubbles), Spending detail, Tax detail.
