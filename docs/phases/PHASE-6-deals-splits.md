# Phase 6 — Savings-deals research + Warikan splits (owner: Sonnet)

Two small features. Deals is deliberately humble engineering around an honest
constraint (no dependable rates API — API.md §4); Warikan builds only if PLAN §4 S3
was accepted (check HANDOFF before starting — if rejected, delete its half from this
doc and skip).

## Deals
1. `data/deals/` JSON schema per API.md §4; `deal_runs`/`savings_deals` import
   (`POST /api/deals/import` + startup scan of newest file), staleness computed
   server-side (>35 days).
2. Write `scripts/research_deals_prompt.md`: the reusable prompt/checklist for the
   monthly research task (what to search — MSE easy-access tables, provider pages;
   what to record — AER, bonus composition, access limits, FSCS, min deposit,
   source URL + fetch date; what to exclude — fixed bonds, regular savers in v1).
   Set up the scheduled Claude task (monthly) per DEPLOYMENT §4d, or document the
   manual ritual if the household prefers.
3. Seed one real research run at build time (current rates, properly cited) so the
   bubble ships alive.
4. DealsPage per DESIGN §4h: date-with-everything discipline, staleness banner, the
   "rough £/year on your balance" line.

## Warikan (if S3 accepted)
1. `split_entries` router per API.md §5: CRUD + `settle` (marks all open entries) +
   `balance`.
2. UI: Splits bubble (collapsed: net balance direction line) + detail ledger; one-tap
   "split this" action in the TransactionTable row menu (pre-fills from the
   transaction, default half). Partner's name from config, **no partner data beyond
   a display name** — this is the primary user's own bookkeeping only (PLAN §4 S3).

## Acceptance
- [ ] Deals bubble shows best rate + checked-date; a run dated 40 days back renders
      the staleness banner (clock-forged test).
- [ ] Every rendered deal has a working source link and a date; no deal without both
      can exist (schema-enforced NOT NULL, import rejects violations).
- [ ] Import is idempotent per file; newest run wins the display.
- [ ] Splits: create → balance updates; settle → zeroed, history retained; one-tap
      from a transaction carries amount/date/description.
- [ ] pytest + typecheck green (paste output).
