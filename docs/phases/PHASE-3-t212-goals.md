# Phase 3 — Trading 212 + goals (owner: Sonnet)

The deposit and rebuild trackers live: T212 polling, balance snapshots, net worth,
and the goal projection engine with its pinned worked example.

## Build
1. `integrations/trading212.py` per API.md §2: `get_account_summary()` **only**.
   Basic auth (key:secret) primary, bare-header legacy fallback behind a config flag;
   5s spacing between calls, 429 honours `x-ratelimit-reset`; floats → pence at the
   edge (`round(x*100)`), never floats past the client boundary. Fixture-tested;
   ⚠️ verify auth scheme + Cash-ISA availability on first real call (HANDOFF Q8) and
   correct API.md §2 in the same commit.
2. Snapshots: sync writes one `balance_snapshots` row per account per `local_date`
   (upsert) — Starling balances too (extend Phase 2's sync). Manual accounts:
   `POST /api/accounts/manual` + `/balance` for anything without an API.
3. `engines/goals.py` per DATA_MODEL §4a — pure functions, and **the pinned test**
   (generic placeholder figures — substitute the real target/baseline/dates from
   PRIVATE.md into local config when seeding, never into the test file itself):
   T=£10,000, B=£1,000, t=2026-07-10, D=2027-01-10 → m=6, required=£1,500. Plus
   month-end derivation tests (Europe/London, month-ends only, median-of-3 trend,
   `no_trend` under 2 snapshots).
4. Seed goals from local config (PRIVATE.md has the real figures — never hardcode
   these): `house_deposit` (target/date/baseline all config-driven), `t212_rebuild`
   (open-ended, same baseline), `emergency_fund` (derived
   target — stub until Phase 4 supplies essential-spend). `routers/goals.py` +
   `routers/accounts.py` (+ `/api/networth` series).
5. Web: Deposit + Rebuild bubbles per DESIGN §3b rows 2–3 (collapsed: progress bar /
   sparkline) and their detail views (§4c GoalBar with target tick + projection
   marker + catch-up sentence; rebuild trend chart with baseline annotation and the
   honest "balance growth" label). Net-worth bubble if PLAN §4 S1 accepted.
   Chart primitives built here: `Sparkline`, `TrendLine`, `GoalBar` (DESIGN §5),
   shaping functions vitest-covered.

## Acceptance
- [ ] With the real, locally-configured house-deposit target/deadline/baseline (never
      hardcoded — PRIVATE.md + `KAKEIBO_GOAL_*` env vars), the Deposit detail renders
      the exact figure `engines/goals.py`'s `required_per_month_minor` computes for
      today's date, ceiled to the pound (never rounded down — ARCHITECTURE.md §6
      "never flatters"). Verify live against a local gitignored `.env`; never assert
      the real number in a committed doc or test.
- [ ] With three faked month-end snapshots trending £900/mo → status `behind`, copy
      "behind — £X/month from now reaches it" with X = ceil((T−B)/m).
- [ ] T212 fixture sync → snapshot row; second run same day → updated in place.
- [ ] Rate-limit test: two forced calls are ≥5s apart (client-level, mocked clock).
- [ ] No float leaves `trading212.py` (type-checked ingest signature + test on a
      `.005` rounding case).
- [ ] pytest + typecheck + vitest green (paste output).
