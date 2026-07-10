# Kakeibo — working notes for Claude

Single-user personal finance dashboard (Starling + Trading 212 + Gmail rental
paperwork → safe-to-spend, goals, tax estimate). **docs/ is the spec and it wins** —
read docs/PLAN.md first, then the doc for whatever you're touching. Build state and
open questions live in docs/HANDOFF.md; real personal specifics live ONLY in
docs/PRIVATE.md (gitignored) — never in anything committed.

## Commands

```
apps/server: .venv/bin/python -m pytest -q            # must stay green
apps/web:    npm run typecheck && npm run test -- --run && npm run build
```

Dev servers are in `.claude/launch.json` (and the shared `~/…/Dev/.claude/launch.json`):
`kakeibo-web` (5178) + `kakeibo-api` (8201, `data/kakeibo.dev.db`). Port registry in
ARCHITECTURE.md §1 — Mishka owns 5173/8000, Michi 5174/8100-8101, Japan 5175. Never
take a sibling's port.

## Hard rules

- **This repo is public.** Personal specifics (employer, partner detail, real goal
  figures/dates, rental dates) live only in gitignored `docs/PRIVATE.md`, local `.env`,
  and DB config rows. Grep before committing anything that smells personal — and never
  use a real date/figure as an "example" value (that's how two of the three leaks
  Phase 8 caught happened).
- **Money is integer pence everywhere** (fields end `_minor`, signed, negative = out).
  A float in a money path is a review-blocker; floats exist only at parse boundaries
  (T212 `round(x*100)`), display formatting, and genuine ratios (`aer_pct`).
- **Read-only against banks, by scope AND code shape.** `app/integrations/*` expose
  `get_*`/`search`/`fetch_*` methods only — no generic request escape hatch, no
  POST/PUT/DELETE. If a feature seems to need a write scope, stop and report.
- **The tax estimator never guesses** (TAX.md §0): missing inputs ⇒ `estimate: null` +
  `missing_inputs`, and the disclaimer ships on every tax surface and response. Rates
  are per-year data in `engines/tax_rates.py` — add a year's dict, never edit logic,
  never copy a year forward silently.
- **No passwords in this repo, ever** — login proxies to Mishka Hub (docs/AUTH.md).
  argon2/password columns mean you've misread the design (tests enforce this).
- **Colours**: semantic tokens only (`bg-paper`, `text-clay`, viz tokens in
  `index.css`). `theme.css` is a synced MIRROR of Michi's canonical copy — never
  hand-edit it here. No raw hex in components (DESIGN.md §7 grep is an acceptance item).
- **No chart libraries** — hand-rolled SVG in `src/charts/`, shaping in testable
  `shape.ts` functions.
- British English microcopy, calm tone, no exclamation marks, no red-alert guilt UI
  (spending renders in ink, not red; "behind" is kraft, not crimson).
- Engines (`app/engines/`) are pure functions — no I/O; services/routers assemble
  inputs. Commit prefix `phase-N:`; run pytest + typecheck before every commit.

## Gotchas (paid for, don't re-pay)

- **Port 8200 will be the production API** (LaunchAgent `com.kakeibo.api`, no
  `--reload` — kickstart after code changes). **8201 is dev** against
  `kakeibo.dev.db`. Never test against the prod db; refresh the dev copy with
  `sqlite3 data/kakeibo.db ".backup 'data/kakeibo.dev.db'"`.
- `current_user` dependency returns an **int user id**, not a User object.
- To see the authenticated app without real credentials: mint a dev session for the
  `preview@example.com` row in the dev db (the Michi-verify pattern — insert a
  RefreshToken via `app.security.generate_refresh_token()`, set
  `localStorage['kakeibo-refresh-token']`). Delete the token row afterwards.
- `main.py`'s lifespan seeds categories/goals/tax-years/deals at startup;
  `seed_deals` is gated off under `KAKEIBO_ENVIRONMENT=test` because it writes a real
  file into `data/deals/` (a test-pollution bug Phase 6 paid for).
- Month/tax-year boundaries are **Europe/London** via `app/dates.py` — no ad-hoc
  `datetime.now()` in domain code.
- The sync engine never raises — a provider outage/missing key becomes a
  `sync_runs` row (`error`/`not_configured`), and the UI degrades to setup cards.
- LaunchAgents under `~/Documents` need the venv's *resolved* python binary granted
  Full Disk Access, and must invoke `.venv/bin/python` directly, never `/bin/sh`
  (Michi's backup agent failed silently under `/bin/sh`).
- The Cloudflare Tunnel config (`~/.cloudflared/config.yml`) is shared by all three
  household apps — after any edit, verify the *siblings'* health endpoints too.
- Rounding: `required_per_month` and its display **ceil** (never flatter —
  `formatMinorWholeCeil`); plain balances round half (`formatMinorWhole`).
