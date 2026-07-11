# Kakeibo — Secrets & Credentials

Every credential the system needs, where to obtain it, and the env var it maps to.
**None of these exist yet** — implementation must not block on them: every integration
degrades to a `not_configured` status (visible in `/api/health` and as a setup card in
its bubble) and the app runs fine without any of them except the JWT secret.

Rules (ARCHITECTURE.md §5):

- All secrets live in `apps/server/.env` (or the file paths named below), on the
  household Mac only. `.gitignore` already excludes `.env*` (except `.env.example`),
  `data/`, `.secrets/`, `credentials/`.
- Nothing here is ever baked into the web build, sent to the browser, logged, or
  committed — `raw` provider payloads stay server-side too (DATA_MODEL.md §8).
- Every bank-side credential is created **read-only at the provider** — the scope is
  the first line of defence, code discipline the second.
- After editing `.env`, restart the API: `launchctl kickstart -k gui/$(id -u)/com.kakeibo.api`.

## The inventory

| Env var | What | How the user obtains it |
|---|---|---|
| `KAKEIBO_JWT_SECRET` | Kakeibo's own session-signing secret (32+ random bytes). **The only var required to boot.** | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` — generate fresh; independent of the siblings' secrets |
| `KAKEIBO_STARLING_PAT` | Starling **Personal Access Token**, read-only scopes (`account:read balance:read transaction:read savings-goal:read` — API.md §1a; corrected in Phase 2 from an earlier guess of `space:read`, confirmed not a real Starling scope name) | <https://developer.starlingbank.com> → sign in with the Starling account → *Personal Access* → create token → tick **read scopes only** → copy once |
| `KAKEIBO_T212_API_KEY` / `KAKEIBO_T212_API_SECRET` | Trading 212 public-API key pair (HTTP Basic — API.md §2) | Trading 212 app → Settings → **API (Beta)** → generate key, read-only permissions only; the secret is shown once — paste both immediately |
| `KAKEIBO_T212_ENV` | `live` or `demo` | `live` for the real account; `demo` (demo.trading212.com) for development |
| `KAKEIBO_GMAIL_CREDENTIALS_PATH` | Path to the Google OAuth **Desktop app** `client_secret.json` | Google Cloud console → project `kakeibo-local` → enable Gmail API → OAuth consent (External, self as test user) → Credentials → OAuth client ID (Desktop) → download JSON → save to `data/secrets/client_secret.json` (gitignored) — full steps API.md §3b |
| `KAKEIBO_GMAIL_TOKEN_PATH` | Where the granted read-only refresh token lands | default `data/secrets/gmail-token.json`; created by running `scripts/gmail_authorise.py` once, interactively (browser consent for `gmail.readonly` only) |
| `KAKEIBO_SERVICE_TOKEN` | Static bearer token for Sukumo's read-only sibling endpoint `GET /api/goal/service` (API.md §5) — Michi's `MICHI_SERVICE_TOKEN` precedent | `openssl rand -hex 24` — generate fresh; the same value goes in Sukumo's `.env` as `SUKUMO_KAKEIBO_SERVICE_TOKEN`; unset = endpoint answers 503 |
| `KAKEIBO_MISHKA_BASE_URL` | Mishka Hub identity endpoint (AUTH.md) | not a secret; default `http://127.0.0.1:8000` |
| `KAKEIBO_DATABASE_URL` | SQLite path | not a secret; default prod db, dev overrides to `kakeibo.dev.db` |
| `KAKEIBO_CORS_ORIGINS` | CORS allow-list override | only if a custom domain is ever added |

Deliberately **not** env vars: payday, salary, flat share, mortgage interest, and all
other personal financial *configuration* — those are DB config rows edited in the app
(DATA_MODEL.md §5). Env is for secrets and infrastructure only.

**One deliberate exception (Phase 3):** a goal's target/baseline (`goals.target_minor`,
`target_date`, `baseline_minor`, `baseline_date` — DATA_MODEL.md §4) currently has no
API-editable bootstrap path — `PATCH /api/goals/{key}` only covers `monthly_pledge_minor`
/ `target_minor` / `source_account_ids`, not the date/baseline fields a goal is *created*
with. Until a proper settings UI exists, `KAKEIBO_GOAL_*` env vars (`.env.example`) seed
these once at first boot (mirrors `KAKEIBO_STARLING_BACKFILL_START`'s precedent — optional,
unset by default, real values live only in a local gitignored `.env`, never committed).
These are not secrets (no rotation/revocation story), just personal figures kept out of
committed source per PRIVATE.md's redaction scheme.

## Rotation & revocation drill (write down now, hope to never need it)

- Starling PAT leaked → revoke at developer.starlingbank.com (token list) → new token
  → `.env` → kickstart. Read-only scope means the blast radius is privacy, not money.
- T212 key leaked → Settings → API → delete key → regenerate. Same read-only calculus.
- Gmail token leaked → <https://myaccount.google.com/permissions> → remove
  `kakeibo-local` → re-run `gmail_authorise.py`.
- `KAKEIBO_JWT_SECRET` rotated → all Kakeibo sessions invalid (log in again);
  siblings unaffected.
- The `.env` file itself is included in nothing but the human's memory — it is NOT in
  the nightly backup by default; decide deliberately whether to add it (Mishka backs
  its `.env` up; doing the same is reasonable **only** if the backup destination is
  as private as the Mac).

The root `.env.example` mirrors this table with placeholder values and per-line
comments — keep the two in lockstep when integrations change.
