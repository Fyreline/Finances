# Phase 4 — Insight engines (owner: **Opus** — judgement-heavy)

The app starts answering questions: safe-to-spend, monthly verdicts, recurring
detection, tips. Everything here is pure-function engines over phase-2/3 data — no new
I/O. Read API.md §6 and DATA_MODEL §3–5 fully first; the formulas there are the spec,
not a suggestion.

## Build
1. `financial_config` router/form (payday, net income, flat share, buffer, set-aside
   mode) — the safe-to-spend inputs. NULLs → `setup_missing`, never defaults
   pretending to be data.
2. `engines/insights.py::safe_to_spend()` per API.md §6a, including the
   payday-anchored period helper (edge cases: payday 29/30/31 in short months → last
   day; mid-period evaluation) and the recurring/flat-share dedup rule. Waterfall
   payload = every formula line, pence-exact (segments sum to income — test it).
3. `engines/recurring.py` per DATA_MODEL §3a — implement the clustering, cadence,
   confidence, and cancel-candidate maths exactly; fixture months covering: stable
   £9.99 sub, price-rise sub, weekly gym, annual insurance, Tesco noise (must NOT
   cluster), missed-month tolerance, salary detection on incoming.
4. `engines/insights.py` tips rules — all seven from API.md §6c as separate functions
   with fixture tests; template sentences only, numbers injected, severities capped at
   `worth_a_look` (except `sa_registration_deadline`).
5. Benchmarks: `engines/benchmarks.py` config module — bands per category with source
   URL + as-of date per entry, seeded from the latest ONS Family Spending release at
   build time (cite it in the file); `month_summary()` per API.md §6b with
   `methodology_note` verbatim discipline (heuristic, approximate, never precise).
6. Web: Safe-to-spend hero bubble goes live (collapsed mini-waterfall + expanded
   labelled waterfall per DESIGN §4a); Spending bubble Breakdown tab (§4d horizontal
   bars + verdict pills + methodology footnote) and Tips tab; Recurring bubble +
   detail (§4f). `WaterfallStrip` + `CategoryBars` primitives; emergency-fund card if
   S2 accepted, contractor gap card if S4 accepted (config-gated).

## Acceptance
- [ ] Safe-to-spend with the full config set returns a waterfall that sums
      pence-exact; with payday unset returns `setup_missing` and the UI shows the
      setup card (both states screenshot-verified).
- [ ] Recurring fixtures: the £9.99 sub detected monthly conf ≥0.8; Tesco not
      detected; price-rise flagged with old→new; dismissed rows stay dismissed after
      re-run.
- [ ] Verdict pills: a category 25% over its band shows `above average` in kraft (not
      crimson); tooltip carries band bounds + source date.
- [ ] Every tip sentence is template-generated (grep the engine for f-strings only, no
      LLM imports) and each rule has a fires/doesn't-fire test pair.
- [ ] Copy audit against DESIGN §6: no "overspending", no "warning", no exclamation
      marks (grep the fixtures' rendered output).
- [ ] pytest + typecheck + vitest green (paste output).
