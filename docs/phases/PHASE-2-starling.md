# Phase 2 — Starling integration (owner: Sonnet)

Transactions flowing: Starling client, sync engine, categorisation, the Spending
bubble's Transactions tab working end-to-end against fixtures (and against the real
account the day a PAT exists — do not block on it).

## Build
1. `integrations/starling.py` per API.md §1: `get_accounts / get_balance / get_feed /
   get_spaces` only — **no generic request method, no write verbs** (ARCHITECTURE §5.2
   grep is an acceptance item). Bearer PAT from settings; absent → raises
   `NotConfigured` which sync records as a `not_configured` run.
2. Fixtures first: record/write realistic JSON for all four endpoints (sandbox-shaped;
   ⚠️ verify field spellings against live docs while here and correct API.md §1b in
   the same commit). Client tests run on fixtures via respx — no live calls in tests.
3. Ingest per API.md §1c: windowed pull with 7-day overlap, month-windowed backfill
   from `KAKEIBO_STARLING_BACKFILL_START` (optional local-only floor, else the
   account's own `createdAt`), normalisation to signed pence + `local_date`, upsert on
   `(account_id, provider_uid)`, declined/refund updates in place, `sync_runs` rows.
4. `engines/categorise.py`: provider `spendingCategory` → default category map (one
   dict, commented), then `category_rules` first-match-wins; rank rule (manual > rule
   > provider, DATA_MODEL §2). Seed rules: transfers-to-own-T212 → `transfer_self` +
   exclude; salary counterparty (config) → `salary`.
5. Routers: `transactions` (list/patch), `categories`, `rules` (+ retro-apply),
   `sync` (run/status). `scripts/sync_providers.py` callable standalone (LaunchAgent
   entrypoint later).
6. Web: `TransactionTable.tsx` per DESIGN §4e (recategorise popover → PATCH → `manual`
   badge), wired into the Spending bubble's detail Transactions tab; sync pill goes
   live off `/api/sync/status`.

## Acceptance
- [ ] Full sync from fixtures → correct row counts; re-run → zero new rows
      (idempotency proven in a test).
- [ ] A manual recategorisation survives a re-sync and a rules retro-apply.
- [ ] `grep -rn "\.post\|\.put\|\.delete" app/integrations/starling.py` → nothing.
- [ ] Spending bubble → Transactions tab: filter by month/category/search round-trips;
      pending rows at 40% opacity; amounts mono, income `+` in gain, spend in ink.
- [ ] Backfill window logic tested (first sync vs incremental).
- [ ] pytest + typecheck green (paste output).
