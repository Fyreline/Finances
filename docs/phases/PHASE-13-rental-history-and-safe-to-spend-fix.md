# Phase 13 — rental-statement history/deductions/cleanup + the real safe-to-spend bug

Owner: Opus (same tier as Phase 4/5/11/12 — real-document parsing + a genuine algorithm
bug in a shared engine). Real user feedback, 2026-07-12, after live use of Phase 12's
output: the tax estimate is now correctly predicting real numbers (Phase 12 confirmed
working), but four things are still wrong, all diagnosed directly against the real
local/prod data by the orchestrator before writing this doc — **don't re-diagnose from
scratch, the root causes below are confirmed, not hypotheses.**

## Item A — pull + show previous tax years too

`gmail_search_days` (`Settings.gmail_search_days`, currently `400`) bounds the Gmail
search to the trailing ~13 months. Confirmed directly: only `tax-documents/2025-26/`
and `tax-documents/2026-27/` exist locally, and the real detected salary history goes
back to **November 2023** (found while diagnosing item C below) — the rental tenancy
very likely predates the current 400-day window too (check the real start date in
`docs/PRIVATE.md`, gitignored, don't commit it). This means at least one, likely two,
earlier tax years of real rent statements have never been pulled at all.

- Widen the search window enough to reach back to the tenancy's actual start (read
  `PRIVATE.md` for the real date; don't hardcode a guessed number of days — derive it,
  or make it comfortably generous, e.g. compute days-since-tenancy-start + margin).
  Gmail's `newer_than:Nd` query syntax (`gmail_pull.py::build_query`) is the same
  mechanism already in use, just needs a bigger `days` value for a backfill run — a
  large one-off value for the historical catch-up, the regular weekly pull can stay
  narrower once history is caught up (it only needs to catch new statements, not
  re-discover old ones — dedup on `gmail_message_id` makes re-running wider harmless
  either way, so simplest is to just raise the default and rely on dedup).
- Run the actual historical pull against the real local/prod Gmail account once this
  lands, same technique as every prior phase (direct DB/script invocation, never a
  forged browser session as the real user) — confirm new tax-year folder(s) appear
  under `tax-documents/` and new `TaxDocument`/`RentalLedgerEntry` rows land via the
  same Phase 12 `rent_statement_ingest.py` pipeline (no logic change needed there
  beyond it running against more history — verify it actually does, don't assume).
- **Web**: confirm/build a way to view a previous tax year's ledger/estimate, not just
  the current one. Check `TaxDetail.tsx` and `routers/tax.py` first — `GET
  /api/tax/years/{tax_year}/summary` already takes a year param, so this may already
  be plumbed and only need a year-selector control wired to it (check `tax_years`
  table/`ensure_tax_year` — does a selector already exist and just have nothing to
  select from before this phase, or does the UI hardcode the current year? Verify
  before building — don't duplicate something that already exists).

## Item B — delete confirmed-non-rental documents

Real, explicit request: delete documents that clearly aren't rental-related (i.e. not
from the letting agent). Phase 12 reclassified 91 false-positive `rent_statement` documents to
`doc_type='other'` rather than deleting them (that phase's spec was deliberately
conservative). The user has now explicitly asked for deletion, which supersedes that
default.

- Delete `TaxDocument` rows (and their on-disk folders under `tax-documents/`) for
  documents that are genuinely **not** rental-related — the `doc_type='other'` bucket
  (bank/broker/energy/game-storefront emails etc., confirmed noise in Phase 12's
  diagnosis) is unambiguously this.
- **Judgement call, already made by the orchestrator, not yours to relitigate**:
  `insurance` (2 real rows) and any `mortgage_interest_cert` documents are a
  *different*, still-genuinely-useful category — landlord insurance and mortgage-
  interest evidence directly feed HANDOFF's still-open Q1/Q4 tax questions (Q1 in
  particular: "the single biggest lever in the tax computation"). These are not "not
  rental" in the sense the user means (junk from unrelated senders); they're real
  property-related paperwork that just isn't a monthly statement. **Do not delete
  these** — the orchestrator is telling the user directly that they're being held back
  and why, as part of reporting this phase's results; don't pause mid-implementation
  to ask, just leave them alone and move on.
- This is a real, irreversible local deletion (DB rows + files). Back up first exactly
  like every prior data-touching phase (`data/backups/kakeibo-pre-phase13-*.db`, and
  copy the `tax-documents/` folders being deleted somewhere recoverable before
  removing them, or at minimum log exactly which folders were removed so it's not a
  silent, unrecoverable action) — script it, report counts, don't hand-delete.

## Item C — deductions from the statement's line-item table aren't being captured

Confirmed directly, real example: the June 2026 statement has a "Property Costs
Summary for Month" section with a genuine itemised deduction (a council-fee-style
general maintenance charge, real figure known to the user but deliberately not
restated here) that Phase 12's parser did not capture — it only extracts `Total Rent`, `Commission % £`, `VAT % £`, and one
optional "landlord-direct repairs line," which doesn't match this section's actual
label format.

**The real statement layout** (confirmed directly from the PDF text, structure only,
no real figures reproduced here):

- A summary block: `Total Rent: £X`, `Commission: N% £X`, `VAT: NN% £X`, `Total Costs
  £X`, `Total Deductons: £X` (yes, that's the real label, not a typo to fix — match it
  exactly), `Net Rent sent to you: £X`.
- A **`Property Costs Summary for Month`** section — one or more lines, each a
  free-text description followed by an amount (e.g. `<Council/contractor name> -
  General Maintenance £XX.XX`). This is the missing piece: **`Total Costs`** on the
  summary block is the sum of this section's line(s), and it's this section, not a
  fixed "repairs line," that needs to be parsed generically (0, 1, or several
  described cost lines per statement, not a single fixed field).
- A **monthly detail table** further down the page (`Month | Money Sent | Process
  Date | Insurance | Repairs & Maintenance + VAT | Commission Fees | Legal & Prof
  Services | Total Credits | Total Rent`, one row per month covered by the statement)
  — cross-check target: this table's `Repairs & Maintenance` column for the statement's
  own covered month should agree with the `Property Costs Summary` section's total,
  and `Total Rent` here should agree with the summary block's `Total Rent`. Use this
  agreement as a confidence signal (`rent_statement_parser.py` already has a
  `confident` concept — extend it, don't replace it): if the two don't reconcile, that's
  a signal to lower confidence rather than silently pick one.
- A **Tax Year Summary** table (cumulative rent/net-rent by tax year) — not needed for
  per-statement extraction, but useful context for item A's multi-year work (it's the
  agent's own running total, a good cross-check once older years are pulled in).

Fix: extend `engines/rent_statement_parser.py` to parse the `Property Costs Summary
for Month` section into one or more `repairs`-typed (or a more accurately-named
allowable-expense type, if the existing `_EXPENSE_TYPES` set — `agent_fees`,
`insurance`, `repairs`, `ground_rent_service`, `other_allowable`, `mortgage_interest`,
`capital_improvement` — doesn't quite fit a council/contractor maintenance charge;
`repairs` is the closest existing match, use it unless there's a clear reason not to)
ledger expense rows, keyed to the statement's covered month, alongside the existing
income/agent_fees rows. **Re-run the backfill** (`scripts/backfill_rental_automation.py`
or its successor) against the already-ingested statements so previously-missed
deductions (June's, and any other month with a costs line) get their ledger rows too —
this needs to be additive/idempotent against documents that already have SOME ledger
rows from Phase 12 (income + agent_fees), not a full re-parse-and-duplicate. Check
existing rows per `tax_document_id` + `expense_type` before inserting.

## Item D — the actual reason safe-to-spend automation "still hasn't happened"

**This is a real, confirmed bug in `engines/recurring.py`, not a data or config gap.**
Diagnosed directly against the real local/prod data:

- `financial_config` for the real user has `payday_day=None`,
  `net_monthly_income_minor=None` (correctly unset — Phase 11's detected-path should
  be covering this).
- `insights_service._detect_income_anchor` returns `None` for the real user — meaning
  `safe_to_spend_payload` falls all the way back to `setup_missing`, exactly the stuck
  "Tell Kakeibo about payday and take-home pay" state the user has been reporting
  every time, despite Phase 11 shipping.
- **Root cause, isolated and confirmed**: the real salary counterparty has **29 real
  monthly payments** from Nov 2023 to Mar 2026 (25 of them cluster tightly on amount,
  easily clearing `_MIN_OCCURRENCES=3`) — genuinely, unambiguously a recurring monthly
  income pattern. But `detect_recurring(direction="in")` returns **zero** patterns for
  it. Traced into `cadence_for_gaps`: this real "last Friday of the month" payday
  produces calendar-day gaps that are **usually 28 or 35 days**, not tightly clustered
  in the current `CADENCE_WINDOWS["monthly"] = (28, 33)` window (a 5-week gap between
  Fridays is common and entirely normal for this cadence, not an anomaly) — Phase 11's
  own spec doc explicitly flagged this exact risk and asked for it to be verified
  against real data once enough history existed ("if the median-gap approach produces
  an obviously-wrong period for a real weekday-anchored payday, that's a sign the
  reasoning needs revisiting") — that verification is what happened here, and the
  reasoning does need revisiting. **Worse, and the more immediate blocker**: this real
  cluster's gaps include a couple of holiday-period outliers (a short ~21-day gap
  paired with a long ~70-day gap, from an early December payment before Christmas
  followed by a longer gap into February) — `cadence_for_gaps`'s outlier rule (`any(g
  > 1.6 × median for g in gaps)`) trips on these, and returns `None` **unconditionally**
  the moment any single gap exceeds the tolerance, regardless of how consistent the
  other 20+ gaps are. That one rule is why the entire 25-strong, obviously-monthly
  cluster produces nothing.

**The fix needs to address both parts, and needs to stay honest (never guess) while
doing it:**

1. Widen the monthly cadence window, or make the window-membership test tolerant of a
   weekday-anchored payday's natural 28-or-35-day alternation (e.g. accept a monthly
   cadence when the median falls in a wider range like 27–36, or — more robust — test
   whether gaps cluster into a small number of *discrete* recurring values (28ish,
   35ish) rather than requiring one tight median window; use judgement on which is
   more correct without overfitting to this one real user's exact pattern, since this
   engine is also used for outgoing committed-cost detection, which mustn't regress).
2. The outlier rule needs to tolerate a small number of real, occasional irregular
   gaps (a holiday-shifted payday, a delayed payment) without discarding an otherwise
   overwhelmingly consistent pattern — e.g. allow up to one (or a small count
   proportional to total occurrences) outlier gap to be excluded from the median/
   cadence computation rather than vetoing the whole cluster, as long as enough
   occurrences remain to still clear `_MIN_OCCURRENCES` and the cadence is still clear
   from what's left. Don't just delete the outlier tolerance rule entirely — it exists
   to stop truly irregular, non-recurring incoming transfers from being falsely
   labelled a pattern; narrow its effect rather than removing the safety it provides.
3. **This function is shared by both `direction="in"` (income anchors) and
   `direction="out"` (committed-cost detection)** — Phase 11 confirmed 8 real
   outgoing patterns already detect correctly today; add a regression test proving
   they still do after this fix (loosening the cadence/outlier logic must not turn
   genuinely irregular non-recurring outgoing spend into false-positive "committed
   costs," which would make safe-to-spend worse, not better, in the other direction).
4. Add the real (redacted/synthetic-figures) case as a permanent regression test: a
   fixture with monthly gaps that alternate ~28/~35 days plus one holiday-shifted
   short+long gap pair, asserting a `monthly` cadence is now detected. Use synthetic
   dates/amounts in the fixture, not the real ones.
5. Once fixed, verify directly (DB/script, not a forged browser session) that the real
   user's `safe_to_spend_payload` now returns a detected `payday_source`/
   `net_income_source` and a real, non-null `safe_to_spend_minor` — this is the actual
   acceptance bar for "safe to spend is finally automated," not just new tests passing.

## Hard constraints — same as every prior phase

- Money integer pence everywhere; no floats in a money path.
- **Never guess.** Item C's parser still degrades to unconfident/manual-review on a
  statement whose costs section doesn't parse cleanly — it doesn't invent a deduction
  figure. Item D's detection still requires real, clustered evidence — it must not
  become more willing to declare a *false* pattern; it should only stop rejecting a
  *real*, occasionally-irregular one.
- No real personal figures/names/amounts/dates in anything committed. Read real PDFs
  and real transaction data locally for diagnosis and layout-learning; never quote
  them into code, tests, docs, commit messages, or your final report. Use synthetic
  fixtures throughout, exactly like every prior phase.
- Item B is a real, irreversible deletion — back up first, script it, report counts,
  and hold the insurance/mortgage_interest_cert question open (ask, don't assume) per
  that section above.
- Read-only against Gmail/every bank/API; a wider search window is still read-only.
- Run pytest + typecheck + vitest + build before committing; full redaction sweep;
  update `docs/HANDOFF.md`, `docs/API.md`/`docs/DATA_MODEL.md` if shapes change
  (a new nullable column self-heals via `app/schema_sync.py`, no manual migration);
  commit prefix `phase-13:`.
- **After this deploys, the orchestrator (not this phase) restarts `com.kakeibo.api`**
  if `apps/server/` was touched (it will be, for items A/C/D) — state this prominently
  in the final report.

## Acceptance

- At least one additional tax year's worth of real rent-statement documents exists
  locally after the widened pull runs, with matching `RentalLedgerEntry` rows, and the
  Tax UI can show it (not just the current year).
- The `other`-typed noise documents (bank/broker/energy/game-storefront emails) are
  gone from both the DB and disk after the backfill/delete script runs; insurance/
  mortgage-interest-cert documents are untouched pending the user's answer.
- The June 2026 statement's real maintenance deduction (and any other month's) now has
  a matching `repairs` ledger row, verified directly against the real ledger (never by
  restating the figure anywhere committed).
- A synthetic regression test proves `detect_recurring` now finds a monthly pattern
  for a last-Friday-style payday with a holiday-period gap pair, AND that the 8 real
  existing outgoing committed-cost detections are unaffected (regression test using
  synthetic data reproducing their shape, not their real values).
- Verified directly against the real prod DB/API (never a forged session): the real
  user's `safe_to_spend_payload` now returns `payday_source`/`net_income_source` ∈
  `{'detected'}` (or `'manual'` if they've since set it themselves) and a real,
  non-null `safe_to_spend_minor` — not `setup_missing` for payday/net income.
