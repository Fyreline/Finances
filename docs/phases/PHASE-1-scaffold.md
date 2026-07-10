# Phase 1 — Scaffold (owner: Sonnet)

Deliver a running skeleton: both apps boot, login round-trips through Mishka Hub,
Aizome tokens + viz extension in place, bubble home screen renders in its all-empty
setup state, dev/prod db split live from the first commit.

## Server (`apps/server`)
1. FastAPI app factory per ARCHITECTURE §2/§4: config (`KAKEIBO_` prefix), db.py,
   `KakeiboHTTPException`, `app/dates.py` (`to_local_date()` Europe/London +
   `tax_year_of()` — unit-test the 5/6 Apr and BST-midnight boundaries now, everything
   later leans on them).
2. models.py: **all** DATA_MODEL.md tables (§1–7, splits included — cheap now, fiddly
   later), plus `categories` seeded with the §3 taxonomy and viz_slots.
3. Auth stack per AUTH.md §2 exactly — port from **Michi** (`security.py` already has
   password functions deleted there), `identity.py`, `routers/auth.py`, `auth.py`.
4. `routers/health.py`: identity probe + `integrations` flags (all `not_configured`).
5. pytest: identity client (respx 200/401/429/timeout), login/refresh/rotation/
   reuse-tripwire, dates helpers. **No argon2 anywhere.**

## Web (`apps/web`)
1. Vite + React 19 + TS + Tailwind v4 + motion; port 5178; `VITE_BASE` env-gated.
   Fonts via fontsource (mirror Michi's package.json set, minus Noto JP).
2. `theme.css`: extend `learningLanguageMachine/scripts/sync-theme.sh` with
   `DST_KAKEIBO`, run it, commit the mirror. `index.css`: DESIGN.md §2a viz/semantic
   tokens, light + dark.
3. Port `auth.ts` + `api.ts` (key `kakeibo-refresh-token`, BASE `http://127.0.0.1:8201`)
   and `ThemeToggle.tsx` (`kakeibo-theme`).
4. Shell per DESIGN.md §3: minimal header (wordmark + 家計簿 + sync pill stub +
   ThemeToggle), `HomePage.tsx` with the bubble grid rendering every roster bubble in
   its `not_configured`/setup state, `Bubble.tsx`, and the expand mechanics —
   desktop in-place panel below the row + `BraceConnector` port from Mishka's
   `App.tsx` (mind the `overflow: visible` gotcha), mobile bottom sheet, `#hash`
   deep-links, focus management (DESIGN §3c). Detail panels are placeholder frames
   this phase; the *interaction* ships now so every later phase drops content into a
   working pattern.
5. `money.ts` with vitest (pence → `£1,234.56`, signs, `tabular-nums` class helper).

## Infra
- launch.json entries `kakeibo-web` (5178) + `kakeibo-api` (8201 → `kakeibo.dev.db`).
- Root `.env.example` (already written), `.gitignore` verified against SECRETS.md.

## Acceptance
- [ ] `uvicorn app.main:app --port 8201` + `npm run dev` → login with real Mishka
      creds succeeds; wrong password → styled error; Mishka down → AUTH.md 503 copy.
- [ ] Session survives reload; three-app localStorage isolation per AUTH.md §4.
- [ ] Home shows the full bubble roster in setup states; bubbles expand/collapse with
      brace (desktop) and sheet (mobile viewport), `#hash` restores on reload,
      keyboard + reduced-motion behaviour per DESIGN §3c.
- [ ] Dark/light repaints every surface incl. §2a viz tokens (visual check both).
- [ ] pytest + typecheck + vitest green (paste output). No argon2. No hex in
      components.
