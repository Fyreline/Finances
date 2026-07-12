# Phase 14 — income-anchor staleness, manual weekday payday, recurring glance clarity

Owner: Opus (same tier as Phase 4/5/11/12/13 — judgment-heavy financial-logic work on
the same `engines/recurring.py`/`insights.py` machinery Phase 11/13 already touched).
Real user feedback, 2026-07-12, after a real job change. Three items — the first two
share one root cause, diagnosed directly against the real prod data before writing
this spec; don't re-diagnose, verify and fix.

## Item 1+4 — the income anchor goes stale after a job change, and it cascades

**This is the same underlying bug surfacing two ways**: the user reports safe-to-spend
showing a nonsensical detected period ("18th Jun to 15th Jul"), and separately that
`remaining_minor`/`per_day_remaining_minor` go deeply negative while the headline
`safe_to_spend_minor` stays positive. Confirmed directly: both trace to one cause.

**The real situation** (structure only — do not restate exact dates/figures beyond
what's needed to describe the bug shape; read the real data yourself for the current
picture rather than trusting these as still-current numbers by the time you implement):
the user changed employer in March/April 2026. Their former employer's salary is a
long, high-confidence, genuinely-monthly pattern (25 occurrences, ~0.81 confidence)
whose `last_seen` is now stale — no payment in months. Their new employer's salary has
started (3 real monthly-cadence payments, dates consistent with the same "last Friday
of the month" pattern as before), but `cluster_by_amount` splits it into a singleton
(the first payment — plausibly prorated/partial, a common real-world first-paycheck
shape) plus a 2-occurrence cluster, which never reaches `_MIN_OCCURRENCES=3` and so
never becomes a detectable candidate at all.

`_detect_income_anchor`'s selection heuristic (`insights_service.py`) picks "the
monthly candidate with by far the largest typical amount" with **no staleness check** —
so it keeps confidently selecting the former employer's long-dead pattern indefinitely,
because it's the only one that clears the bar. `payday_period_from_detected` then rolls
that anchor's stale `last_seen` forward by repeated median gaps until it reaches
"today," producing a period that has no relationship to the user's actual current pay
cycle — which is exactly the "18th Jun to 15th Jul" nonsense reported. `remaining_minor`
and `per_day_remaining_minor` are computed against that bogus period's discretionary
spend, while `safe_to_spend_minor` itself is a flat monthly figure independent of the
period — which is why the headline number looks fine while the pacing figures don't:
they're being computed against completely the wrong window, not actually wrong in their
own arithmetic.

### Fix, three parts

**1a. Staleness-aware anchor selection.** A candidate whose `last_seen` is
meaningfully older than its own cadence would predict (e.g. more than ~1.5–2× the
cadence's nominal period since `last_seen` — a monthly pattern that hasn't repeated in
~45–60 days is not "the current salary" any more, no matter how many times it
historically repeated) should not be selected as the current income anchor. Use
judgement on the exact threshold — it needs to tolerate a normal one-cycle payroll
delay (a slightly late payment) without discarding a still-live pattern, while
correctly retiring a genuinely-ended one. If staleness disqualifies every candidate,
fall through to `setup_missing` for the fields that were relying on detection — this
is the honest "we don't currently have a confident answer" state, not a crash or a
silently-wrong one. A **manually-set** `net_monthly_income_minor` (which this user has
already done, working around the bug) must keep working exactly as today regardless of
this change — staleness only affects the *detected* path.

**1b. Tolerate one early amount-outlier when a cluster is otherwise fresh and
consistent.** A brand-new job's first payment is a real, common case for differing
from the steady-state amount (proration, a different pay cycle at onboarding). Extend
`cluster_by_amount` (or add a variant used specifically for recency-sensitive
candidates) to allow the earliest occurrence in an otherwise-tight, otherwise-recent
run to sit outside the normal amount tolerance without preventing the remaining
occurrences from forming a valid cluster — mirroring Phase 13 item D's bounded
gap-outlier tolerance, but on the amount dimension this time. Be careful this doesn't
loosen general subscription-amount clustering elsewhere (Tesco's variable grocery
spend must still scatter, docs/DATA_MODEL.md §3a.1's own worked example) — scope the
tolerance narrowly (e.g. only the single earliest transaction in a cluster, only when
enough later occurrences agree tightly) rather than loosening the general rule.
**Even with this fix, a real 2-payment-old job will sometimes still not have enough
history for 3 confident occurrences** — that's fine and correct; it should fall to
`setup_missing`/no-detection honestly rather than being forced.

**1c. A real, standing gap even after 1a/1b: a manual weekday-based payday override.**
The user has asked for this directly, twice: the only manual override today is
`payday_day` (a 1–31 day-of-month integer), which cannot represent "last Friday of the
month" at all — exactly the real payday shape this user (and presumably future
job-change gaps) needs to fall back to when detection can't yet help. Add a genuine
alternative manual configuration path:

- A new way to express "the Nth weekday of the month" or "the last weekday of the
  month" (e.g. `payday_weekday` 0–6 + `payday_week_position` ∈
  `{'first','second','third','fourth','last'}`) as nullable `financial_config` columns
  (self-heals via `app/schema_sync.py`, no manual migration) — mutually exclusive with
  the existing numeric `payday_day` (setting one should sensibly clear/ignore the
  other; use judgement on the exact UX, but don't leave both simultaneously "set" in a
  way that's ambiguous about which wins).
- A pure function alongside the existing `payday_period` (`engines/insights.py`) that
  computes the current period from a weekday rule — e.g. "the period ending on the
  most recent occurrence of that weekday-position on or before `today`, running back
  to the previous such occurrence" (mirror `payday_period`'s existing period-boundary
  semantics exactly, just with a different rule for finding the anchor date). Add it
  to `resolve_period`'s manual branch (manual still always wins over detected, per
  Phase 11's established precedent — this is just a second *kind* of manual, not a new
  precedence tier).
- `ConfigForm`/`SafeToSpendDetail` (web): a toggle between "day of month" and "day of
  week" input modes for the manual payday field, each writing to its own
  field-pair. Keep the detected-state banner (Phase 11) working exactly as before for
  whichever fields remain undetected/unset.
- Confirm explicitly: rental income timing (already summed by `_period_rental_income`
  independent of whichever anchor/period is active, per Phase 11's design) is
  unaffected by any of this — it's not itself a period generator and this phase
  doesn't need to touch it, just verify with a test that it still isn't.

**Verify directly against the real prod DB** (script invocation, never a forged
session): after 1a/1b, does detection now behave sensibly given the real current
data (either a confident new-employer anchor, or an honest `setup_missing` rather than
the stale one)? And confirm the new manual weekday path, once set, produces a sane
period and makes `remaining_minor`/`per_day_remaining_minor` sane too (the actual
acceptance bar — not just that the numbers changed, but that they now describe a real
current pay period).

## Item 2 — recurring payments preview is confusing

Real complaint: "Recurring payments preview should give the full amount... I'm not
quite sure where the value and name of the business it displays here are." Diagnosed
directly against the real detected list:

- `RecurringGlance` (`apps/web/src/components/InsightGlances.tsx`) shows a "next"
  line with **only a label and a date — no amount**. Add the amount (use
  `Math.abs(next.typical_amount_minor)`, formatted the same way `RecurringRow` does)
  so the glance answers "how much, for what, when" instead of leaving out the "how
  much" — this directly addresses "give the full amount."
- The real detected list mixes genuine subscriptions (clear merchant names, e.g. a
  streaming/reading service) with the user's own internal transfers and cash
  movements between accounts (a savings standing order, an investment-platform
  transfer, a cash-withdrawal PIN reference) that got swept in because they're
  amount-and-cadence-regular, exactly like `docs/DATA_MODEL.md §3a`'s algorithm
  intends to catch — but their raw counterparty text reads as an unrecognisable
  "business" (a savings-transfer label, a garbled card-terminal string), which is very
  likely the "not sure ... name of business" half of the complaint. Two independent,
  compatible improvements — do both if reasonably scoped, don't treat this as
  either/or:
  1. **Selection**: when picking which item is "next" for the glance, prefer an
     `active`-status item (not `lapsed`) if one exists, rather than picking purely by
     soonest `next_expected` regardless of whether the pattern is still live — a
     lapsed pattern's `next_expected` can easily be the soonest chronologically (it's
     stale) while being the least relevant thing to headline.
  2. **Label clarity**: the existing "not a subscription" verdict (Phase 10 item 4)
     already exists for exactly this — a user dismissing "Trading 212" or a savings
     transfer as `not_recurring` removes it from consideration going forward. Check
     whether the glance/detail already surface this affordance clearly enough for a
     first-time viewer to understand *why* an unfamiliar name is showing up (a brief,
     honest label like "possibly a transfer, not a bill" is more useful than silently
     doing nothing) — improve the copy/affordance if it's not obvious, rather than
     trying to algorithmically guess which merchants are "really" businesses (that's a
     harder, lower-confidence problem than just making the existing dismiss action
     easier to discover and use).

## Hard constraints — same as every prior phase

- Money integer pence everywhere; no floats in a money path.
- Never guess. The whole point of 1a/1c is refusing to confidently use a wrong
  detected answer — `setup_missing` is the correct output when nothing trustworthy is
  available, exactly like every prior phase's discipline.
- No real personal figures/names/employers/dates in anything committed — this phase
  touches genuinely sensitive material (a real employer change). Use synthetic
  fixtures throughout (a synthetic "old employer"/"new employer" pair of clusters
  reproducing the shape: one long/stale, one short/fresh with an early amount
  outlier).
- Read-only against every bank/API; this phase is pure local computation over
  already-synced data plus a schema addition, no new external calls.
- Run pytest + typecheck + vitest + build before committing; full redaction sweep
  (this project has had two close calls this week — grep everything before
  committing, not just the new files); update `docs/HANDOFF.md`, `docs/API.md`/`docs/
  DATA_MODEL.md` for the new `financial_config` fields and any response-shape changes;
  commit prefix `phase-14:`.
- **After this deploys, the orchestrator (not this phase) restarts `com.kakeibo.api`**
  — this phase touches `apps/server/`. State this prominently in the final report.

## Acceptance

- A synthetic fixture reproducing the real shape (one long-stale monthly cluster, one
  short-fresh cluster with an early amount outlier) proves: the stale cluster is no
  longer selected as the current anchor once it's gone quiet; the fresh cluster is
  either detected confidently (once 1b's tolerance applies) or the system honestly
  falls to `setup_missing` rather than using the stale one — never a silently-wrong
  period.
- A new synthetic regression test proves the 8 real already-working outgoing
  committed-cost detections (Phase 13's baseline) are still unaffected by 1b's
  amount-tolerance change.
- A manually-configured weekday payday (e.g. "last Friday") produces a correct,
  sensible period, verified against a hand-computed expectation in a test — and
  verified live against the real prod config once set, that `remaining_minor`/
  `per_day_remaining_minor` describe the real current pay period sensibly.
- `RecurringGlance`'s "next" line shows an amount. A synthetic test/story proves the
  glance prefers an active pattern over a lapsed one with an earlier `next_expected`
  when both exist.
