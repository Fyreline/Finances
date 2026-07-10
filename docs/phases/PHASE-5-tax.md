# Phase 5 — Tax pipeline (owner: **Opus** — correctness-critical)

Gmail pull, rental ledger, and the SA estimator. **TAX.md is the spec and it wins.**
Two absolute rules from it: the estimator never guesses missing inputs (null +
`missing_inputs`, not fabricated numbers), and the disclaimer ships on every surface.

This phase can be built and fully tested **before** HANDOFF Q1–Q4 are answered — the
open questions are config fields; only *real numbers* wait on them. Do not invent
placeholder answers in seed data.

## Build
1. `tax_config` + `financial_config` already exist (DATA_MODEL §5); build the
   `routers/tax.py` config endpoints and the TaxPage setup form (each unanswered field
   labelled with why it matters — lift the sentences from TAX.md §2's table).
2. `engines/tax_rates.py`: per-year rate tables as data (2025-26 Scottish bands from
   TAX.md §3 — and check whether the 2026-27 Scottish Budget figures are published;
   if yes add them with a source comment, if no wire the visible "using 2025-26
   rates" assumption per TAX.md §7).
3. `engines/tax.py`: both routes per TAX.md §5 — marginal stacking
   (`scottish_tax(a+b) − scottish_tax(a)`), S24 credit with the three-way min +
   carry-forward, allowance route with the conservative no-credit assumption
   (⚠️ verify the SA105-notes interaction while building, update TAX.md §5c),
   loss carry-forward, POA test (80% at-source rule), `nic_due: 0` + note.
   **All three §5d worked examples as unit tests, hand-computed in comments.**
4. `rental_ledger` router + UI (SA105-shaped table, add-entry, link to transaction or
   document); `is_rental` transactions offered as one-tap ledger candidates; CSV
   export per TAX.md §6.
5. Gmail: `integrations/gmail.py` (search/fetch/attachment only, `gmail.readonly`),
   `scripts/gmail_authorise.py` (Desktop OAuth flow per API.md §3b — resolve the
   Testing-vs-production refresh-token question while here and update §3b),
   `scripts/pull_rental_emails.py` per §3c (query from config, dedup on message id,
   save under `tax-documents/<tax-year>/`, classify, parse amounts conservatively,
   `reviewed=0`). Mock the Gmail service in tests (no live Google in CI).
6. TaxPage per DESIGN §4g: Documents (review queue) / Ledger / Estimate
   (side-by-side route comparison, winner outlined, every line visible) + deadline
   checklist from TAX.md §6 + the disclaimer block. Tax bubble collapsed spec per
   DESIGN §3b row 6.

## Acceptance
- [ ] TAX.md §7 checklist — every box, it is the real acceptance list for this phase.
- [ ] Additionally: pipeline run against a mocked mailbox produces correctly-dated
      folders across a 5/6 April boundary; re-run adds nothing.
- [ ] An unreviewed document cannot reach the ledger (API enforces `reviewed=1` on
      `tax_document_id` links — test).
- [ ] `gmail.py` exposes exactly three read methods; no modify/send/labels imports.
- [ ] pytest + typecheck green (paste output, tax tests named readably —
      `test_worked_example_band_straddle` etc.).
