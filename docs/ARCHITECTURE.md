# Kakeibo — Architecture

The shape deliberately mirrors Michi (`Dev/learningLanguageMachine`) and Mishka Hub
(`Dev/MishkaHub`): a Vite/React SPA talking JSON to a local FastAPI + SQLite backend on
the household Mac, deployed the same way (static web on GitHub Pages; API behind the
shared Cloudflare Tunnel). Anyone who has worked on either sibling can navigate this
repo blind. Stack verified against the siblings' real manifests
(`learningLanguageMachine/apps/web/package.json`, `apps/server/requirements.txt`):
**React 19 + TypeScript + Vite + Tailwind v4 + motion** on the web; **FastAPI +
SQLAlchemy 2.x + SQLite + httpx + pyjwt + pydantic-settings** on the server.

## 1. Household port & hostname registry

| App | Web dev | API (prod, LaunchAgent) | API (dev) | Public hostname |
|---|---|---|---|---|
| Mishka Hub | 5173 | 8000 | — | (Mishka's own) |
| Michi | 5174 | 8100 | 8101 | `michi-api.mishka-hub.com` |
| **Kakeibo** | **5178** | **8200** | **8201** | **`kakeibo-api.mishka-hub.com`** |

Never take a sibling's port. The dev/prod split (8201 vs 8200) exists **from day one** —
Michi paid for this lesson twice (test runs corrupted the live household db). The
LaunchAgent on 8200 serves `data/kakeibo.db` (real money data, no `--reload`); local dev
runs on 8201 against `data/kakeibo.dev.db`. Refresh the dev copy any time with
`sqlite3 data/kakeibo.db ".backup 'data/kakeibo.dev.db'"`.

## 2. Repo layout

```
Finances/
├── README.md
├── .env.example               # every credential slot, documented (SECRETS.md)
├── docs/                      # you are here — the spec that drives implementation
│   └── phases/                # per-phase build orders with acceptance criteria
├── apps/
│   ├── web/                   # Vite + React 19 + TypeScript + Tailwind v4 + motion
│   │   ├── index.html
│   │   ├── package.json
│   │   ├── vite.config.ts     # dev port 5178; base '/Finances/' env-gated for Pages
│   │   └── src/
│   │       ├── main.tsx
│   │       ├── App.tsx        # route switch + nav shell + auth gate
│   │       ├── index.css      # Kakeibo-only tokens (viz ramp etc., DESIGN.md §2)
│   │       ├── theme.css      # Aizome palette MIRROR — synced from Michi, never hand-edited
│   │       ├── auth.ts        # PORT of Michi apps/web/src/auth.ts, key 'kakeibo-refresh-token'
│   │       ├── api.ts         # fetch wrapper w/ bearer + 401 retry (port of Michi's)
│   │       ├── money.ts       # pence<->display formatting, tabular GBP (§6)
│   │       ├── charts/        # hand-rolled SVG chart primitives (§7): Sparkline,
│   │       │                  #   CategoryBars, TrendLine, ProgressBar, Donut — no chart lib
│   │       └── components/
│   │           ├── LoginScreen.tsx
│   │           ├── HomePage.tsx          # THE screen: bubble grid + expand logic —
│   │           │                         #   bubbles are the app's navigation, no tab
│   │           │                         #   bar (DESIGN.md §3)
│   │           ├── Bubble.tsx            # collapsed tile shell (glance variants)
│   │           ├── BraceConnector.tsx    # port of Mishka's expansion brace (DESIGN §3c)
│   │           ├── details/              # one expanded view per bubble (DESIGN §3b):
│   │           │   ├── SafeToSpendDetail.tsx · DepositDetail.tsx · RebuildDetail.tsx
│   │           │   ├── SpendingDetail.tsx     # tabs: breakdown / transactions / tips
│   │           │   ├── RecurringDetail.tsx · TaxDetail.tsx · DealsDetail.tsx
│   │           │   └── NetWorthDetail.tsx · SplitsDetail.tsx  (if S1/S3 accepted)
│   │           ├── TransactionTable.tsx
│   │           ├── StatTile.tsx / VerdictPill.tsx / GoalBar.tsx
│   │           └── ThemeToggle.tsx       # straight port from Michi ('kakeibo-theme')
│   └── server/                # FastAPI
│       ├── requirements.txt   # fastapi, uvicorn, sqlalchemy, pydantic-settings, pyjwt,
│       │                      # httpx, google-api-python-client, google-auth-oauthlib,
│       │                      # pytest, respx — NO argon2 (AUTH.md), NO pandas (overkill)
│       ├── app/
│       │   ├── main.py        # app factory, CORS, routers
│       │   ├── config.py      # env prefix KAKEIBO_ (§4)
│       │   ├── db.py          # engine/session helpers (port of Michi's)
│       │   ├── models.py      # DATA_MODEL.md
│       │   ├── security.py    # JWT access + rotating refresh (port, no password fns)
│       │   ├── auth.py        # current_user dependency
│       │   ├── identity.py    # Mishka Hub identity client (AUTH.md)
│       │   ├── integrations/
│       │   │   ├── starling.py    # read-only client (API.md §1)
│       │   │   ├── trading212.py  # read-only client (API.md §2)
│       │   │   └── gmail.py       # read-only client + OAuth flow (API.md §3)
│       │   ├── engines/
│       │   │   ├── categorise.py  # provider category + rules → local category
│       │   │   ├── recurring.py   # cadence detection (DATA_MODEL.md §3)
│       │   │   ├── goals.py       # projection maths (DATA_MODEL.md §4)
│       │   │   ├── insights.py    # safe-to-spend, verdicts, tips (API.md §6)
│       │   │   └── tax.py         # SA estimator (TAX.md §5 — pure functions, heavily tested)
│       │   └── routers/
│       │       ├── auth.py        # login (proxied verify) / refresh / logout / me
│       │       ├── accounts.py    # accounts, balances, net worth
│       │       ├── transactions.py
│       │       ├── summary.py     # safe-to-spend, monthly breakdown, tips
│       │       ├── recurring.py
│       │       ├── goals.py
│       │       ├── tax.py         # ledger, estimate, documents, config
│       │       ├── deals.py
│       │       ├── splits.py      # Warikan (if PLAN §4 S3 accepted)
│       │       ├── sync.py        # on-demand sync triggers + sync status
│       │       └── health.py
│       └── scripts/
│           ├── sync_providers.py    # Starling+T212 pull; run by com.kakeibo.sync
│           ├── pull_rental_emails.py# Gmail pipeline; run by com.kakeibo.gmail
│           ├── gmail_authorise.py   # one-time interactive OAuth consent (API.md §3)
│           └── backup_db.py         # port of Michi's backup script
├── data/                      # gitignored: kakeibo.db, kakeibo.dev.db, backups/,
│   └── deals/                 #   dated savings-deals research JSON (API.md §4)
└── tax-documents/             # gitignored: <tax-year>/ folders of pulled paperwork
    ├── 2025-26/               # first SA year — letting started partway through (PRIVATE.md)
    └── 2026-27/
```

## 3. How the pieces talk

```
 browser SPA (GitHub Pages, or 5178 in dev)
   │  POST /api/auth/login (email+pw) ────────► Kakeibo server (8200)
   │                                              │ POST /api/auth/login ──► Mishka Hub (8000)
   │  ◄─ Kakeibo access(15m) + refresh(30d) ◄─────┘ (verify only, AUTH.md)
   │
   │  GET /api/summary/safe-to-spend ───────────► engines/insights over local SQLite
   │  GET /api/transactions?month=2026-07 ──────► local rows (synced, never live-proxied)
   │  GET /api/goals, /api/tax/estimate, ... ───► pure reads of local data
   │  POST /api/sync/run ───────────────────────► pulls Starling/T212 now (also on schedule)
   │
   └── the browser NEVER talks to Starling / Trading 212 / Gmail. Ever.

 on the Mac, on schedules (launchd, DEPLOYMENT.md §4):
   com.kakeibo.sync   every 6h → scripts/sync_providers.py
        │ GET api.starlingbank.com/api/v2/...      (Bearer PAT, read-only scopes)
        │ GET live.trading212.com/api/v0/equity/account/summary  (Basic key:secret)
        └ writes accounts / transactions / balance_snapshots
   com.kakeibo.gmail  weekly  → scripts/pull_rental_emails.py
        │ GET gmail.googleapis.com (gmail.readonly, local OAuth token)
        └ writes tax-documents/<tax-year>/... + tax_documents rows
   com.kakeibo.backup 03:15 daily → scripts/backup_db.py (sqlite .backup API)
```

Decisions worth stating:

- **Sync-then-serve, never live-proxy.** Provider APIs are hit only by the scheduled
  scripts (or an explicit `POST /api/sync/run`), results land in SQLite, and every
  dashboard read is a local query. Rationale: T212's rate limit (as low as 1 req/5s on
  the summary endpoint), Starling courtesy, offline resilience, and it keeps provider
  credentials out of every request path but one.
- **The frontend is derived-data-only.** The SPA receives categorised transactions,
  aggregates, and verdicts — never provider tokens, never raw provider payloads
  (`raw_json` stays server-side). The public Pages build contains zero personal data;
  everything the user sees is fetched at runtime after login.
- **Engines are pure functions** over rows + config, in `app/engines/`. No engine does
  I/O; routers assemble inputs and call them. This is what makes the tax maths testable
  to the standard TAX.md demands.
- **The two servers share a machine, not a database.** Kakeibo's only dependency on
  Mishka Hub is the identity call at login (AUTH.md). Its own SQLite holds everything
  else.
- **No chart library.** The charts Kakeibo needs (bars, lines, sparklines, progress,
  one donut) are small hand-rolled SVG components against the Aizome viz tokens —
  same philosophy as Michi's hand-built PathScene. Recharts/d3 would be the first
  dependency an implementer reaches for; don't (DESIGN.md §5 has the specs).

## 4. Server conventions

- Settings via pydantic-settings, env prefix `KAKEIBO_`, `.env` in `apps/server/`
  (full credential list in [SECRETS.md](SECRETS.md)):
  - `KAKEIBO_JWT_SECRET` (32+ random bytes; independent of both siblings' secrets)
  - `KAKEIBO_MISHKA_BASE_URL` (default `http://127.0.0.1:8000`)
  - `KAKEIBO_CORS_ORIGINS` (defaults: `http://localhost:5178`, `http://127.0.0.1:5178`,
    `https://fyreline.github.io`)
  - `KAKEIBO_DATABASE_URL` (default `sqlite:///<repo>/data/kakeibo.db`; dev entry in
    launch.json overrides to `kakeibo.dev.db`)
  - `KAKEIBO_STARLING_PAT`, `KAKEIBO_T212_API_KEY` / `_API_SECRET` / `_ENV`,
    `KAKEIBO_GMAIL_CREDENTIALS_PATH` / `_TOKEN_PATH` (integration slots — absent =
    that integration reports `not_configured`, app still runs)
  - `KAKEIBO_ACCESS_TOKEN_TTL_MINUTES=15`, `KAKEIBO_REFRESH_TOKEN_TTL_DAYS=30`
- Error shape `{"detail": str, "code": str}` — `KakeiboHTTPException`, same pattern.
- SQLAlchemy 2.x mapped-column style; tables created on startup; timestamps UTC
  `"%Y-%m-%d %H:%M:%S"` strings (household convention). **Calendar/month boundaries are
  computed in Europe/London** — a transaction at 23:30 BST on the 31st belongs to that
  month, not UTC's next one. One helper (`app/dates.py`, `to_local_date()`), used
  everywhere; no ad-hoc `datetime.now()`.
- User-financial *configuration* (payday, flat-share amount, salary, tax config) lives
  in DB tables (DATA_MODEL.md §5), editable via the API — **not** in env vars. Env is
  for secrets and infrastructure only.

## 5. Trust boundary & read-only guarantee

The line is the Mac. Everything secret stays on the left of it:

| Left of the line (household Mac only) | Right of the line (public) |
|---|---|
| Starling PAT, T212 key+secret, Gmail OAuth client + token | GitHub Pages build (public repo — audited: no secrets, no personal data, in full history) |
| `data/*.db`, `data/deals/`, `tax-documents/` (all gitignored) | The SPA's JS — knows only `VITE_API_BASE` |
| `.env` (gitignored; `.env.example` is the committed template) | JSON responses over the tunnel, after Mishka-session login |

Enforcement, not vibes:

1. **Scopes:** Starling PAT created with read scopes only (API.md §1); T212 key
   generated with read-only permissions ticked; Gmail `gmail.readonly`. Even a bug
   cannot move money if the credential can't.
2. **Code:** `integrations/*.py` expose only `get_*` methods; there is no generic
   `request()` escape hatch on the clients. `grep -rn "POST\|PUT\|DELETE" app/integrations/`
   returning anything but the OAuth token exchange is a review-blocker.
3. **Build:** phase-8 verification greps the built `dist/` for key fragments and
   personal identifiers before first Pages deploy, same audit Mishka Hub passed.
4. Tunnel/CORS/auth posture identical to Michi: API bound to 127.0.0.1, TLS at
   Cloudflare, explicit CORS origin allow-list, bearer tokens not cookies.

## 6. Money & number conventions

- **All amounts are integer minor units (pence)** in DB, API JSON, and engine maths —
  Starling already speaks `minorUnits`; T212 floats are converted at the client edge
  (`round(x * 100)`) and never touched as floats again. Field names end `_minor`.
- Direction convention: signed pence from Kakeibo's perspective — negative = money out.
  (Starling's `direction: IN/OUT` + unsigned `minorUnits` normalise at ingest.)
- Display formatting is `money.ts`'s job alone: `£1,234.56`, minus sign not parentheses,
  `font-mono tabular-nums` in tables/tiles (DESIGN.md §3).
- Percentages: one decimal place max; "on track" maths rounds *against* the user
  (ceil on required-per-month) so the app never flatters.

## 7. Testing & verification bar

- Server: pytest for `identity.py` (Mishka up/down/bad password — respx-stubbed),
  every engine (`categorise`, `recurring`, `goals`, `insights`, `tax` — the tax module
  gets worked-example tests pinned to TAX.md §7's hand-computed cases), and each
  integration client against recorded JSON fixtures (no live calls in tests, ever).
- Web: `npm run typecheck` clean; vitest for `money.ts` and chart-data shaping.
- End-to-end gate before "done": login with real Mishka creds → sync (fixtures or real
  keys if supplied) → dashboard shows safe-to-spend → recategorise a transaction →
  verdicts update → tax estimate matches the hand-computed example → deploy checks
  (PHASE-8).
