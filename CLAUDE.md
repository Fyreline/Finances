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
- **A `git push` that deploys the frontend does NOT restart the backend.** They ship
  independently — Pages redeploys on push automatically, but `com.kakeibo.api` keeps
  running whatever code was on disk when it last started until you
  `launchctl kickstart -k gui/$(id -u)/com.kakeibo.api`. Forgetting this after a
  frontend-and-backend change lands is a real incident, not a theoretical one: the
  2026-07-11 "blank page after login" bug was exactly this — a stale backend missing
  Phase 9's new response fields, crashing the freshly-deployed frontend that expected
  them (docs/HANDOFF.md's "Production incident" entry has the full story). **Kickstart
  the API every time a commit touches `apps/server/` and prod is meant to serve it —
  don't assume a push handled it.**
- `current_user` dependency returns an **int user id**, not a User object.
- To see the authenticated app without real credentials: mint a dev session for the
  `preview@example.com` row **in the dev db only** (the Michi-verify pattern — insert a
  RefreshToken via `app.security.generate_refresh_token()`, set
  `localStorage['kakeibo-refresh-token']`). Delete the token row afterwards. **Never do
  this against the real user's row in the prod db** — even for debugging, even
  read-only-looking — that's forging a live session for someone else's real account,
  which the Claude Code safety classifier will (correctly) refuse the moment it's used
  to authenticate a browser session, per the 2026-07-11 incident note above. If you need
  to see what a real user's API response looks like, ask them to share it, or ask them
  to grant that debugging approach explicitly first.
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
