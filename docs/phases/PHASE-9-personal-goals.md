# Phase 9 — Net worth, emergency fund, contractor gap, gift/wants goals

Owner: Sonnet. Builds the items accepted from PLAN.md §4 (S1, S2, S4) plus goals 10-11
(PLAN.md §3, deferred at the original 8-phase build). Not judgment-heavy in the way
Phase 4/5 were — mostly new read-only aggregates over data phases 2-3 already sync, plus
one genuinely new mechanic (the affordability check). No new external integrations.

Real credentials now exist (docs/HANDOFF.md, 2026-07-10/11) and have been validated —
Starling and Trading 212 sync real data successfully; Gmail OAuth is live but gated on
Q3's sender config. This phase still builds and tests entirely against fixtures/the dev
db, same discipline as phases 1-8 — real numbers only ever flow through local config,
never into a fixture or test file.

## Scope

### 1. S1 — Net worth strip (PLAN.md §4 S1)

Aggregate across every `accounts` row with `include_in_networth=1` (Starling, T212,
manual) using each account's latest `balance_snapshots` row. One number, one 90-day
sparkline (reuse `charts/Sparkline.tsx`/`shape.ts`), a breakdown list (account name +
balance) on expand. New bubble in the roster; collapsed glance = total + sparkline.

- `engines/networth.py`: pure function, `net_worth_series(snapshots) -> list[{date,
  total_minor}]` and `net_worth_now(accounts, snapshots) -> {total_minor,
  by_account: [...]}`.
- `routers/networth.py`: `GET /api/networth` (current + 90-day series + by-account).
- Web: `NetWorthGlance.tsx`, `components/details/NetWorthDetail.tsx`, wired into
  `HomePage.tsx`'s bubble roster and `GET /api/summary/bubbles` (Phase 7's one-fetch
  aggregate — extend `bubbles_payload()`, don't add a second round-trip).

### 2. S2 — Emergency fund adequacy check (PLAN.md §4 S2)

`months_of_cover = accessible_cash / essential_monthly_spend`, where accessible_cash =
net worth of `kind='current'` + `kind='savings'` accounts only (excludes T212 —
investments aren't "accessible" in the emergency-fund sense), and essential_monthly
= `financial_config`'s fixed commitments (already captured for safe-to-spend, Phase 4)
+ a groceries baseline (categories.kind='discretionary' but groceries specifically is
essential-adjacent — use the existing `benchmarks.py` groceries band's midpoint as the
essential estimate, cited the same way benchmarks already are). Verdict bands: <1mo
"building from scratch" (not "critical" — PLAN.md §6 rule 8, no guilt UI), 1-3mo
"below the usual 3-6 month guide", 3-6mo "within the usual range", 6mo+ "well covered".
**Deliberate copy point** (PRIVATE.md context, don't lose this in implementation): while
a goal like the house deposit dominates savings, a low months-of-cover reading is often
a *deliberate trade-off*, not a mistake — the verdict copy must say something like "a
deliberate trade-off while you're saving toward other goals" when a house/rebuild goal
is active and behind, never read as an alarm.

- `engines/emergency_fund.py`: pure function, `emergency_fund_check(accessible_cash_minor,
  essential_monthly_minor, has_active_savings_goal: bool) -> {months_of_cover: float,
  verdict: str, copy: str}`.
- Feeds into the existing Safe-to-spend or a new bubble — **use your judgement per
  DESIGN.md §3b's existing roster**: either its own small bubble, or a line inside the
  Net Worth detail view (they share the same accessible-cash data). Document the choice
  in DESIGN.md when you land it.
- Router: extend `routers/summary.py` or `routers/networth.py`, whichever bubble hosts it.

### 3. S4 — Contractor gap card (PLAN.md §4 S4)

Static-config-plus-one-rule card: reads `financial_config.pension_contributing`
(new nullable boolean field — **default NULL, never assume False**, per PRIVATE.md: the
user does not currently know his own pension status and flagged he needs to check —
render "not sure yet — check with your consultancy" as a first-class state, not a
missing-data error) and `financial_config.fte_conversion_target_date` (nullable, ~April
2028-ish per PRIVATE.md context but must be user-set, never hardcoded). If a conversion
date is set, seed an `fte_runway` goal (same `goals` table/engine as house_deposit —
reuse `engines/goals.py`'s projection maths, don't fork it) targeting a cash buffer by
that date; target amount is user-config, never invented.

- Extend `financial_config` (DATA_MODEL.md) with `pension_contributing: bool | null` and
  `fte_conversion_target_date: str | null` (+ PATCH support alongside the existing
  financial-config form, Phase 4's `/api/financial-config`).
- `routers/summary.py` or a small `contractor_gap` field on the existing config
  response — a card, not a heavy new engine. If `fte_conversion_target_date` is set,
  surface the `fte_runway` goal via the existing goals endpoints (no new router needed).
- Web: a compact card (not a full bubble — check DESIGN.md §3b's roster; if adding an
  8th/9th bubble feels like too much chrome for a "quiet" card per the original PLAN.md
  §4 S4 wording, fold it into an existing bubble's detail view instead, e.g. Net Worth's
  or Safe-to-spend's — use your judgement and document the choice).

### 4. Goal 10 — occasion gift budgets (PLAN.md §3 row 10)

New goal `kind='occasion'` + a child table `gift_items` (item label, price_minor,
bought: bool, occasion link). One occasion = one sinking-fund-style budget with a
limit (user-set, no default invented — PRIVATE.md: "no limit figure given yet, don't
invent one"); items add up against the limit with a running total and an
over/under-limit verdict (calm, PLAN.md §6 rule 8 — over-limit is information, not
guilt). Occasions themselves (which birthday, which Christmas) are user-created, not
seeded — this repo has no business knowing occasion names/dates beyond what the user
types into the UI (real examples — partner's name, real past gift prices — must never
appear as seed data or test fixtures; use fully generic placeholders like "Occasion A",
"gift item").

- DATA_MODEL.md: add `gift_occasions` (id, user_id, label, limit_minor, target_date) and
  `gift_items` (id, occasion_id, label, price_minor, bought: bool, bought_date).
- `engines/gifts.py`: pure `occasion_summary(occasion, items) -> {spent_minor,
  limit_minor, remaining_minor, verdict}`.
- `routers/gifts.py`: CRUD for occasions + items.
- Web: fits inside whichever bubble houses "personal wants" (§5 below) as a tab, or its
  own small section — **share the affordability-check mechanic from §5**, don't build
  two separate systems (a gift item is functionally a wants-list item scoped to an
  occasion budget instead of the general pot).

### 5. Goal 11 — personal wants + the affordability check (PLAN.md §3 row 11, refined)

The core new mechanic this phase adds: **not** a simple capped-pot budget. A wishlist
item (`want_items`: label, price_minor, bought: bool, created_at) gets an
**affordability verdict** computed against two things together:
1. **This month's safe-to-spend headroom** (Phase 4's `engines/insights.py`
   safe-to-spend — is there enough discretionary room left this period, right now).
2. **Whether buying it would meaningfully delay an active savings goal** — run the
   existing `engines/goals.py` projection with the item's price subtracted from the
   relevant pot's current balance (if the want would plausibly come out of savings
   rather than this month's spare cash — a >discretionary-headroom item), and compare
   `required_per_month`/`catch_up` before vs after. A verdict like "yes, this fits" /
   "not yet — would push the house deposit back roughly N weeks" / "fits if it comes
   out of this month's spare cash, not savings".

Keep this a **pure function over already-computed inputs** — `engines/affordability.py`,
`check_affordability(price_minor, safe_to_spend_headroom_minor, goal_projection_before,
goal_projection_after) -> {verdict: str, detail: str}` — composed from Phase 3's goals
engine and Phase 4's insights engine, not a new parallel money model. Same function
powers goal 10's gift items (an occasion's remaining budget instead of general
safe-to-spend headroom).

- DATA_MODEL.md: `want_items` (id, user_id, label, price_minor, bought, created_at).
- `engines/affordability.py` as above.
- `routers/wants.py`: CRUD + a `GET .../affordability` computed field per item.
- Web: wants list with an inline affordability pill per item (reads the same verdict
  vocabulary/tone as everywhere else — calm, no guilt, DESIGN.md §6).

## Hard constraints (same as every prior phase, restated because this phase touches
new user-facing money surfaces)

- Integer pence everywhere, no floats in a money path.
- No real personal figures/names ever committed — occasions/items/limits are 100%
  user-entered at runtime, never seeded, never present in a fixture or test with
  anything but clearly synthetic placeholder text.
- No guilt UI. Over-budget, behind-on-emergency-fund, "not affordable yet" all render
  as calm information (ink/kraft), never crimson-as-alarm (crimson stays reserved for
  genuine over-target per the existing semantic rules, and even then it's "information"
  per DESIGN.md, not a scolding).
- `financial_config`'s new nullable fields (`pension_contributing`,
  `fte_conversion_target_date`) must render an honest "not answered yet" state, never
  a false default.
- Read-only against every bank/API integration, as always — this phase adds zero new
  external calls, it's entirely local aggregation over what phases 2-3 already sync.
- Extend Phase 7's one-fetch `GET /api/summary/bubbles` rather than adding new
  unbatched round-trips to the home screen.
- Run pytest + typecheck + vitest + build before committing; update docs/HANDOFF.md's
  state table; commit prefix `phase-9:`.

## Acceptance

- New engines are pure functions with unit tests exercising real edge cases (net worth
  with zero accounts, emergency fund at exactly 3.0 months, affordability check when
  the item costs more than the entire goal target, gift occasion with zero items).
- Bubble roster / detail views render sensibly in a fresh setup state (nothing
  configured yet) without crashing — matches every existing bubble's degrade-gracefully
  discipline.
- A full grep sweep for personal specifics across every new file, before commit.
