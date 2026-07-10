# Kakeibo — Build Plan

**Codename: Kakeibo** (家計簿 — the traditional Japanese household finance ledger, kept
faithfully, reviewed monthly). It sits naturally beside **Mishka Hub** (the cat) and
**Michi** (道, the path): the household's third app is quite literally a kakeibo — a
calm, honest ledger of what came in, what went out, and whether the plan is on track.
Alternatives considered: *Zeni* (銭, coin — too jokey), *Okane* (お金 — too literal),
*Tsumiki* (積み木, building blocks — pretty but opaque). Kakeibo says what it is.

Docs-first (this suite), then phased implementation with explicit owners, same as Michi.
Model policy per household preference: **Sonnet for well-specified ports/scaffolds and
API integrations, Opus for the judgment-heavy insight/tax engines, Fable for the
dashboard visuals and final verification.** Every phase ends at its doc's acceptance
criteria, independently verified by the orchestrator (run the code, not the report —
subagent claims are not evidence).

> ⚠️ **Standing disclaimer, repeated wherever tax appears:** Kakeibo estimates for
> planning purposes only. It is not an accountant, not HMRC, and its tax numbers must
> never be copied into a real Self Assessment return without independent checking
> (accountant or HMRC's own calculators). See [TAX.md](TAX.md) §0.

## 1. Who this is for (the real brief)

A single named user (see [PRIVATE.md](PRIVATE.md), gitignored — real name, employer,
dates and figures live there, never here), UK-based. One user's real financial life —
not a demo:

- **Work:** a contractor arrangement with a large employer via a consultancy, hoping for
  direct conversion to a permanent role after a multi-year qualifying period (exact
  timeline and PAYE-vs-Ltd mechanics: [HANDOFF.md](HANDOFF.md) Q5). Until conversion:
  likely thinner pension contributions and benefits than a permanent employee — a gap
  this app should surface, not ignore (§3 goal 9 / Fable's suggestions).
- **Housing:** owns a house he no longer lives in; moved in with his partner into a flat
  owned by a family member of hers; **rents his own house out** as of a specific date in
  2025 (PRIVATE.md). Rental income is not taxed via PAYE → **UK Self Assessment**, with
  real deadlines ([TAX.md](TAX.md) §6 — the first affected tax year is 2025-26; the
  registration deadline for that year, if not already registered, is **5 October 2026**).
- **Partner finances:** separate bank accounts; groceries and shared costs are split
  roughly and informally, untracked today. Her money is **out of scope** — Kakeibo never
  tracks, estimates, or displays the partner's finances. (An opt-in split/IOU tracker for
  *shared expenses only* is proposed in §4.)
- **Savings state:** a savings pot that had been his primary vehicle was spent on a large
  one-off purchase and is now being rebuilt from a low baseline (exact figure and date:
  PRIVATE.md).
- **The headline goal:** save a specific target amount by a specific date as his half of
  a house deposit (his partner's half is already saved and explicitly out of scope; the
  real target/deadline live in PRIVATE.md and in runtime config, never hardcoded in
  source or docs).
- All UK: British English, GBP, UK tax year (6 April–5 April), HMRC terminology,
  Scottish income tax bands (he is a Scottish taxpayer — this changes the rental tax
  maths, [TAX.md](TAX.md) §3).

> **Why this section reads generically:** this repo is public. Real personal specifics
> (name, employer, exact dates/figures, family living detail) live only in
> [PRIVATE.md](PRIVATE.md), a gitignored local file, and in runtime config the app loads
> at startup — never in committed docs, seed data, or source code. See HANDOFF.md's
> repo-visibility note before adding any new doc with real numbers in it.

## 2. What Kakeibo is (and is not)

A **read-only monitoring and planning dashboard**: it pulls balances and transactions
from Starling and Trading 212, rental paperwork from Gmail, and turns them into
safe-to-spend numbers, goal trajectories, spending verdicts, and a tax-year file ready
to hand an accountant.

It is **never** a payments app. No feature, endpoint, or scope in this suite can move
money, place an order, or write anything back to a bank. This is a hard constraint
(ARCHITECTURE.md §5); a PR that adds a write-capable bank scope is a design violation,
not a feature.

## 3. The nine goals → features, docs, phases

| # | Goal | Feature (spec) | Phase |
|---|---|---|---|
| 1 | "How much can I safely spend this month?" | Safe-to-spend engine: payday-anchored month, income − committed obligations − goal contributions − tax set-aside − buffer = discretionary; daily-rate countdown. Formula in [API.md](API.md) §6a; UI in [DESIGN.md](DESIGN.md) §4a. | [PHASE-4](phases/PHASE-4-insights.md) |
| 2 | House deposit: **user-configured target by user-configured deadline** (real values: PRIVATE.md) | Goal tracker with progress bar + projection: required £/month from today's position, trailing-3-month contribution trend, "on track" / "behind — £X/month needed to catch up" verdict. Maths in [DATA_MODEL.md](DATA_MODEL.md) §4. | [PHASE-3](phases/PHASE-3-t212-goals.md) |
| 3 | Trading 212 rebuild from a low baseline | T212 `equity/account/summary` polled daily → balance snapshots → contribution trend chart. Integration spec [API.md](API.md) §2. | [PHASE-3](phases/PHASE-3-t212-goals.md) |
| 4 | Best easy-access savings deals | **Agent-assisted periodic research**, not a live feed (no dependable UK comparison API exists): a scheduled research task writes dated, source-cited findings into `data/deals/`; the dashboard renders them with their as-of date always visible. Spec [API.md](API.md) §4. | [PHASE-6](phases/PHASE-6-deals-splits.md) |
| 5 | Monthly spending by category + maintainable/average/above-average verdict | Categorisation engine (Starling's `spendingCategory` + local rules) and an explicit, documented, *heuristic* benchmark methodology — loosely ONS-style bands adjusted for a young professional couple in Scotland, stored as config with sources and dates, never presented as precise. [API.md](API.md) §6b. | [PHASE-2](phases/PHASE-2-starling.md) + [PHASE-4](phases/PHASE-4-insights.md) |
| 6 | Actionable money tips | Rule-based insight engine (category trending up vs 3-month average, cancel-candidate subscriptions, high discretionary variance, emergency-fund shortfall). Advisory tone, never prescriptive, no ML dressed as advice. Rules enumerated in [API.md](API.md) §6c. | [PHASE-4](phases/PHASE-4-insights.md) |
| 7 | Recurring payment detection | Pattern matching over the Starling feed: same counterparty + similar amount (±12%) + ~monthly cadence (28–33 days) → recurring row with confidence score and cancel-candidate flags. Algorithm in [DATA_MODEL.md](DATA_MODEL.md) §3. | [PHASE-4](phases/PHASE-4-insights.md) |
| 8 | Rental income & tax consolidation | Three parts: **(a) organise** — read-only Gmail pull of rental paperwork into `tax-documents/<tax-year>/`, per UK tax year, accountant-ready; **(b) estimate** — Scottish income tax on rental profit with the Section 24 finance-cost restriction vs the £1,000 property allowance, both computed, better one shown (and the NIC position stated correctly — ordinary letting is *not* liable to Class 2/4 NIC, [TAX.md](TAX.md) §4); **(c) track** — allowable-expense ledger fed from transactions + documents. Blocked on the [HANDOFF.md](HANDOFF.md) mortgage/SA open questions — the engine takes them as config, never guesses. | [PHASE-5](phases/PHASE-5-tax.md) |
| 9 | Freeform | §4 below — each item individually acceptable/rejectable. | various |
| 10 | Occasion gift budgets | User-requested (2026-07-10), **deferred — not needed for initial build**: an occasion-scoped sinking fund per gift-giving event (partner's birthday, Christmas — real occasions/dates: PRIVATE.md), each with a spending limit and an itemised list of planned/bought items + prices (typically one larger item in the low hundreds of pounds, plus smaller items). Verdict against the limit as items are added, same visual language as the deposit GoalBar. Structurally this is the `goals` table with a `kind='occasion'` variant + a child `gift_items` table — cheap to add once Phase 3's goal engine exists. Candidate for **Phase 9** or folded into Phase 6. | future |
| 11 | Personal wants / project budget | User-requested (2026-07-10), **deferred**: a running wishlist of things the user wants for himself or for hobby/side-project spending, each with a price. Refined (2026-07-10): rather than a simple capped pot, the core mechanic is an **affordability check** — cross-reference an item's price against current safe-to-spend headroom *and* whether buying it would knock the house-deposit/T212-rebuild goals off track, returning a "yes, affordable" / "not yet — would push goal X back" verdict rather than just tracking spend against a fixed budget. The same mechanic likely fits goal 10's gift budgets too, for consistency. Same structural pattern as goal 10 (`kind='personal_wants'`). Candidate for **Phase 9** or folded into Phase 6. | future |

### 3a. The home screen: bubbles

Per product direction (2026-07-10), the app's primary navigation is a **bubble home
screen**: one compact rounded tile per domain (safe-to-spend hero, house deposit, T212
rebuild, spending+tips, recurring, tax year, deals — plus net worth and splits if S1/S3
are accepted), each expanding into its full detail view. The canonical bubble roster,
collapsed-content specs, and the expand interaction are in [DESIGN.md](DESIGN.md)
§3 — **sanity-check the goal→bubble grouping there** (notably: spending breakdown and
tips share one bubble with internal tabs).

## 4. Fable's suggestions — accept/reject each individually

None of these are silently folded into the required scope. Accepted items get built in
the phase noted; rejected items are deleted from the phase docs before that phase runs.

### In-app features

- [x] **S1 — Net worth strip** (Phase 3, cheap) — **accepted 2026-07-10.** Starling
  balance + T212 total + a manual entry for anything else, snapshotted daily, one
  sparkline. The deposit and rebuild goals already need the snapshot table, so this is
  nearly free. Not yet built (accepted after Phase 3 shipped) — candidate for Phase 9
  alongside the other accepted-late items, or a small standalone addition.
- [x] **S2 — Emergency-fund adequacy check** (Phase 4) — **accepted 2026-07-10.**
  Months-of-essential-spend covered by accessible cash (essential = fixed commitments +
  groceries baseline), verdict against the standard 3–6 month band. Honest nuance:
  while the deposit goal dominates, this will read "below 3 months" for a while — copy
  should say "deliberate trade-off while saving for the deposit", not guilt. Not yet
  built (accepted after Phase 4 shipped) — candidate for Phase 9.
- [ ] **S3 — Warikan (割り勘) partner split tracker** (Phase 6): a lightweight IOU
  ledger for the informal grocery/shared-cost split. This user's side only — log a
  shared cost, record who paid, track the running balance, settle whenever. **Never
  touches her accounts or data**; entries are manual or one-tap from a Starling
  transaction. **Still undecided** — not selected when S1/S2/S4 were accepted
  (2026-07-10); stays unbuilt until explicitly accepted.
- [x] **S4 — Contractor gap card** (Phase 4, static config + one rule) — **accepted
  2026-07-10.** A quiet dashboard card noting the contractor-vs-FTE gaps that cost real
  money — pension contributions (is anything going into a pension at all? if the
  consultancy runs auto-enrolment, at what %?), no sick pay/income protection
  assumptions, and an **FTE-conversion runway sub-goal** (a small cash buffer targeted
  at ~April 2028 in case conversion slips). Needs HANDOFF Q12 (pension) answered before
  it can show real figures; employment type (Q5) is now confirmed PAYE. Not yet built —
  candidate for Phase 9.
- [ ] **S5 — Tax set-aside pot tracking** (Phase 5): the tax estimator already computes
  the accruing SA liability; this suggestion surfaces it as a "money that isn't yours"
  line inside safe-to-spend, so January's bill never surprises. **Not yet addressed** in
  the 2026-07-10 accept/reject round — still undecided.

### Companion projects (separate repos, household portfolio)

- [ ] **C1 — Wedding hub.** A wedding may be coming (PRIVATE.md context).
  A private planning app in the household style (guest list, venue shortlist, budget —
  the budget view could read Kakeibo's API for a "wedding" goal). Natural fourth app;
  strongest candidate.
- [ ] **C2 — Meal planner / recipe box.** Groceries are the couple's biggest untracked
  shared cost. A weekly meal planner with a shopping list would pair with Kakeibo's
  groceries category (did planned weeks cost less?) and with Warikan (S3).
- [ ] **C3 — Landlord logbook.** A tiny maintenance/repair log for the rented-out house
  (date, photo, cost, contractor). Directly synergistic: every logged repair is an
  allowable expense candidate that Kakeibo's tax ledger can import. Could also start
  life as a Kakeibo module rather than a separate site.

## 5. Phases and owners

| Phase | Scope | Owner | Doc |
|---|---|---|---|
| 1 | Monorepo scaffold: web shell + tokens + login (Mishka identity proxy), server with auth/models/health, dev/prod db split from day one | Sonnet | [PHASE-1](phases/PHASE-1-scaffold.md) |
| 2 | Starling integration: client, sync engine, transaction store, categorisation + rules, recategorise UI | Sonnet | [PHASE-2](phases/PHASE-2-starling.md) |
| 3 | Trading 212 + goals: T212 poll, balance snapshots, net worth, goal engine (deposit/rebuild/emergency fund), projections | Sonnet | [PHASE-3](phases/PHASE-3-t212-goals.md) |
| 4 | Insight engines: safe-to-spend, monthly breakdown + benchmarks, recurring detection, tips | **Opus** | [PHASE-4](phases/PHASE-4-insights.md) |
| 5 | Tax pipeline: Gmail pull, rental ledger, SA estimator, tax-year folders | **Opus** | [PHASE-5](phases/PHASE-5-tax.md) |
| 6 | Savings-deals research feature + Warikan splits (if S3 accepted) | Sonnet | [PHASE-6](phases/PHASE-6-deals-splits.md) |
| 7 | Dashboard UI: charts, stat tiles, goal visuals, polish per DESIGN.md | **Fable** | [PHASE-7](phases/PHASE-7-dashboard.md) |
| 8 | End-to-end verification against every doc's acceptance list, deploy (Pages + LaunchAgents + tunnel), push | Fable | [PHASE-8](phases/PHASE-8-verify-ship.md) |

Sequencing: 1 → 2 → 3 (2 and 3 could parallelise, but 3's snapshot table reuses 2's sync
scaffolding — sequential is safer) → 4 and 5 in parallel (independent engines over the
phase-2/3 data) → 6 → 7 → 8. Phase 5 **cannot produce real numbers** until HANDOFF Q1–Q4
are answered; it can still build the whole pipeline against config placeholders.
Phases land as commits on `main` (single-user repo, no PR ceremony), message prefix
`phase-N:`.

## 6. Ground rules for implementing agents

1. Read the referenced docs **fully** before writing code; the docs win over instinct.
   A contradiction between docs is a stop-and-report, not a coin flip.
2. Ports from Michi (`/Users/mack/Documents/Dev/learningLanguageMachine`) and Mishka Hub
   (`/Users/mack/Documents/Dev/MishkaHub`) are explicitly listed in each phase doc —
   copy the real files and adapt; do not reinvent.
3. No new dependencies beyond the stack in ARCHITECTURE.md without written justification
   in the commit message.
4. Meet the acceptance criteria *and leave proof*: each phase's completion report must
   include commands run and their real output (typecheck, pytest, curl).
5. **Money is integer pence everywhere** (ARCHITECTURE.md §6). A float in a money path
   is a review-blocker.
6. **Read-only against banks** — if an implementation choice would need a write scope,
   stop and report.
7. Real API keys do not exist yet ([SECRETS.md](SECRETS.md)); every integration must
   run against recorded fixtures until the user supplies them, and degrade to a
   friendly "not connected yet" card rather than crash.
8. British English microcopy, calm tone, no exclamation marks, **no red-alert guilt UI**
   — an over-budget month is information, not a scolding (DESIGN.md §6).
