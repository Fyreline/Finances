# Phase 11 — auto-detect payday and net income from real transaction history

Owner: Opus (judgment-heavy financial-logic change to the safe-to-spend engine, same
tier as the original Phase 4/5). Real user feedback, 2026-07-11, after live use with
real synced data: payday isn't a fixed day-of-month ("last Friday, or maybe Thursday,
of the month"), rental income lands anywhere in a window (2nd–10th, "depending on
processing"), and the user's explicit ask is for Kakeibo to derive as much of this as
possible from actual Starling history rather than requiring rigid manual config.

## What's already true — read this before writing any code

Two of the three things the user asked for are **already fully working**, verified live
against the real account by the orchestrator before writing this doc:

1. **Committed/fixed costs already auto-populate from detected recurring outgoing
   transactions** (`insights_service.py::safe_to_spend_payload` calls
   `detect_for_user()`, whose results become `committed` — see `engines/insights.py`'s
   `safe_to_spend()` signature). Verified live: 8 real recurring patterns are already
   detected on the real account with real confidence scores, no code change needed here.
2. **Rental income already sums real `is_rental`-tagged transactions within the
   period** (`insights_service.py::_period_rental_income`), which correctly handles
   the 2nd–10th variable timing by construction — it's driven by when the transaction
   actually landed, not a date rule. The reason it was reading £0 for the real user: no
   `category_rules` row existed to tag the letting-agent transfer as rental income at
   all (the CategoryRule/retro-apply mechanism already exists in
   `routers/transactions.py`, it just had nothing configured). **The orchestrator
   already fixed this directly against the live database** (one rule, retro-applied,
   11 real transactions correctly tagged) — nothing to build here either, just be aware
   it's now populated and don't regress it.

**The one real gap**: `FinancialConfig.payday_day` is a literal 1–31 integer
(`app/engines/insights.py::payday_period`), which cannot represent "last Friday of the
month" (a different day-of-month every month) at all, and `net_monthly_income_minor`
requires manual entry even though the actual salary amount is directly observable from
real transaction history. Both gate `safe_to_spend_minor` entirely — until they're set
(manually, today), nothing computes, regardless of how much real Starling data exists.

## The fix: derive payday period + net income from a detected income anchor

`engines/recurring.py::detect_recurring()` already supports `direction="in"` — income
anchors — per its own docstring ("Salary/rent arriving are detected the same way on
**incoming** transactions... offered as income anchors, never auto-assumed"). **This
capability has never actually been called anywhere** — `insights_service.py::
detect_for_user()` only ever calls it with `direction="out"`. That's the wiring gap.

### 1. `engines/insights.py` — a detected-period path alongside the manual one

Add a new pure function, something like:

```python
def payday_period_from_detected(
    last_seen: date, occurrences_gaps_days: list[int], today: date,
) -> tuple[date, date]:
```

that derives the *current* period from the salary anchor's own observed history rather
than a modelled day-of-month rule: `period_start` = the most recent detected salary
transaction's date; `period_end` = `period_start + median(occurrences_gaps_days) - 1`,
rolling forward by the same median gap repeatedly if `today` has already passed that
estimated end (covers "checked the app a bit into the next period before the next real
salary transaction has synced yet" — a real, expected case, not an edge case to paper
over). This deliberately does **not** try to model "last Friday of the month" as an
explicit weekday rule: the actual calendar-day gaps between consecutive real
"last-Friday" salary dates already cluster in the same 28–33 day window
`CADENCE_WINDOWS["monthly"]` already uses, so median-gap-of-real-observations handles
this (and weekly, and genuinely-irregular-but-roughly-monthly) uniformly, without a
special case. Verify this reasoning against the real detected pattern once Starling
history is long enough to have 2+ real salary occurrences — if the median-gap approach
produces an obviously-wrong period for a real weekday-anchored payday, that's a sign the
reasoning above needs revisiting, not that the user's data is wrong.

### 2. `insights_service.py` — wire the income-anchor detection in

Add an `_detect_income_anchor(session, user_id, as_of) -> DetectedIncome | None` that
calls `recurring.detect_recurring(transactions, direction="in", as_of=today)` and picks
the single best candidate: **by far the largest typical amount** among patterns with
monthly-ish cadence and confidence above a sensible floor (reuse the existing
`_CONFIDENCE_FLOOR`/clustering thresholds already in `engines/recurring.py` — don't
invent new ones without reason) — this is "salary", distinct from the smaller
recurring incoming amounts (refunds, etc.) that would also technically match
`direction="in"`. Document the exact selection heuristic in the function's docstring
so it's auditable, not a black box.

In `safe_to_spend_payload`:
- If `config.payday_day` and `config.net_monthly_income_minor` are both explicitly set
  (manual), use them exactly as today — **manual always wins**, matching the
  "certificate always wins over estimate" precedent from Phase 10's mortgage-interest
  work. Never silently override an explicit user value with a detection.
- Else, if a confident income anchor is detected, use
  `payday_period_from_detected(...)` for the period and the anchor's `typical_amount_minor`
  for net income — but **surface this as detected, not silent**: the API response needs
  a way to say "this figure came from your transaction history, not something you told
  us" (see §3). This mirrors TAX.md's `assumptions` array pattern — don't invent a new
  transparency mechanism, reuse that shape/spirit.
- Else (genuinely not enough history yet, or too irregular to detect confidently), fall
  back to today's `setup_missing` exactly as now — this must never regress; it's the
  correct behaviour for a brand-new account.

### 3. API contract (`docs/API.md` §6a, `SafeToSpend` response shape)

Add fields communicating provenance, e.g. `payday_source: 'manual' | 'detected' | null`
and `net_income_source: 'manual' | 'detected' | null` (null alongside `setup_missing`
when neither applies yet). The detail response should also surface *what* was detected
in human terms good enough for the UI to show "detected from a recurring payment
averaging £X, roughly every N days" — don't just return raw numbers with no
explanation of where they came from; the whole point of this phase is transparency
about auto-detection, not a second kind of opaque black box replacing the first.

### 4. Web (`SafeToSpendDetail.tsx`, `ConfigForm`)

When payday/income are detected (not manual), show them as a **calm, clearly-labelled
detected state** with an obvious "these are guesses from your history — override below
if wrong" affordance, rather than silently presenting a detected figure as if the user
had typed it in themselves. Manual override through the existing `ConfigForm` must
still work exactly as today and, once saved, must take precedence over detection from
that point on (matches §2's "manual always wins" rule — verify explicitly setting
`payday_day` server-side actually flips `payday_source` to `'manual'` and stops the
detected path from ever overriding it again).

## Hard constraints — same discipline as every prior phase

- Money integer pence everywhere, no floats in a money path.
- **Never silently guess a number and present it as certain.** A detected value must
  always be visibly marked as detected (same principle as TAX.md §0's "never guess" and
  the mortgage-rate-estimate `assumptions` line from Phase 10) — the difference between
  "detected, here's why, override if wrong" and "guessed and presented as fact" is the
  entire point of this phase.
- No real personal figures/names ever committed — as always, any new test fixtures use
  clearly synthetic transaction data (synthetic salary amounts/dates/cadences).
- Read-only against every bank/API — this phase is pure local computation over already-
  synced data, no new external calls.
- Don't regress the two already-working pieces (committed-cost auto-detection, rental
  income transaction-summing) — add tests that they still work exactly as today if you
  touch any shared code path (e.g. if `detect_for_user` or its shared helpers change
  shape to support the new `direction="in"` call site).
- Run pytest + typecheck + vitest + build before committing; full redaction sweep;
  update docs/HANDOFF.md's state table, docs/API.md §6a, docs/DATA_MODEL.md if the
  `financial_config`/response shapes change; commit prefix `phase-11:`.
- **This phase does not touch the database schema** (no new columns) — if it turns out
  to need one (e.g. to cache the detected anchor), use `app/schema_sync.py`'s existing
  auto-migration safety net rather than requiring a manual `ALTER TABLE` step, and
  confirm live that a restart picks it up cleanly before considering the phase done.
- **After this deploys, the orchestrator (not this phase) restarts
  `com.kakeibo.api`** — this phase touches `apps/server/`, and per the two prior
  incidents this session (docs/HANDOFF.md), a push alone never restarts the running
  backend. State this prominently, first or last, in the final report.

## Acceptance

- A synthetic test fixture with 3+ monthly incoming "salary" transactions on
  irregular-but-clustered dates (simulating "last Friday of the month" without
  hardcoding that exact rule) produces a sensible detected period and net income,
  visibly marked as detected.
- Setting `payday_day`/`net_monthly_income_minor` manually always wins over detection,
  immediately, and stays won on subsequent computations.
- A fresh account with no income history yet still correctly falls back to today's
  `setup_missing` behaviour — this is not allowed to regress.
- The two already-working pieces (committed-cost detection, rental-income summing) have
  passing tests proving they're unaffected by this phase's changes.
