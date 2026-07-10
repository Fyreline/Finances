# Kakeibo — Auth: one household identity, shared with Mishka Hub

Same requirement, same answer as Michi: **there is only one credential store — Mishka
Hub's.** Kakeibo never stores, hashes, or even *sees a hash of* a password. At login,
Kakeibo's server verifies the submitted email/password by calling Mishka Hub's own login
endpoint, then issues its own independent token pair. A password changed in Mishka Hub
is instantly the credential for Kakeibo — no second copy, no sync job, no drift.

This document is deliberately thin: Michi's
[`AUTH.md`](/Users/mack/Documents/Dev/learningLanguageMachine/docs/AUTH.md) is the
canonical write-up of the pattern (alternatives table, flow, security posture), and
Michi's *implementation* is the port source — it's one proxy hop closer to reality than
the doc. Everything below is the Kakeibo-specific delta.

## 1. The flow (unchanged from Michi)

```
LoginScreen ──(email, password over HTTPS)──► Kakeibo POST /api/auth/login
    Kakeibo server ──POST {KAKEIBO_MISHKA_BASE_URL}/api/auth/login (httpx, 5s timeout)──► Mishka Hub
        200 → verified ✓ · 401 → passthrough 401 · 429 → passthrough 429
        conn error/timeout → 503 code="identity_unavailable",
            detail "Mishka Hub isn't reachable — Kakeibo borrows its login. Is it running?"
    on verified: upsert users row keyed by lower(email)
        {email, display_name, mishka_user_id — refreshed every login}
    issue KAKEIBO tokens: JWT access (15 min, KAKEIBO_JWT_SECRET) +
        opaque rotating refresh token (30 d), reuse-detection tripwire included
    discard the Mishka-side token pair (best-effort logout call to keep its table tidy)
```

## 2. Kakeibo-specific deltas

| Item | Value |
|---|---|
| Env prefix / secret | `KAKEIBO_JWT_SECRET` — independent of both `MISHKA_JWT_SECRET` and `MICHI_JWT_SECRET`; rotating one never touches the others' sessions |
| Identity base URL | `KAKEIBO_MISHKA_BASE_URL`, default `http://127.0.0.1:8000` (loopback — both servers live on the same Mac). `identity.py` refuses a plain-http non-loopback base URL at startup, same guard as Michi |
| localStorage key | `kakeibo-refresh-token` — distinct from `mishka-*` and `michi-*` so three SPAs coexist in one browser without clobbering each other's sessions |
| Theme key | `kakeibo-theme` (ThemeToggle port) |
| Rate limit | same 5-failures/15-min/IP deque *in front of* the proxy call, so Kakeibo can't be used to hammer Mishka |
| Port sources | `security.py`, `identity.py`, `routers/auth.py`, `auth.py` from **Michi** (they already have the password functions deleted); frontend `auth.ts`/`api.ts` from Michi with BASE default `http://127.0.0.1:8201` (dev) |

## 3. Why the bar is higher here

Kakeibo is the household's most sensitive app — behind login sits a full financial
picture and, indirectly, the machine that holds bank credentials. Two additions on top
of the Michi posture:

1. **Access tokens stay at 15 minutes — do not be tempted upward.** A leaked Kakeibo
   access token exposes balances and transaction history (read-only, but private).
2. **Session-required on literally everything** except `login/refresh/health`. There is
   no anonymous surface: no public stats, no unauthenticated summary endpoint, and
   `GET /api/health` returns liveness + integration reachability flags only — never
   balances or counts.

Worth saying once: even a fully compromised Kakeibo session **cannot move money** —
the provider credentials are read-only by scope and the clients have no write methods
(ARCHITECTURE.md §5). Auth protects privacy; the read-only design protects the money.

## 4. Acceptance criteria

- [ ] Logging into Kakeibo with current Mishka Hub credentials succeeds; wrong password
      → 401 `code="invalid_credentials"`.
- [ ] Change the password via Mishka's `set_password.py` → old password immediately
      fails on Kakeibo, new one works, zero Kakeibo-side action.
- [ ] Stop Mishka Hub's server → Kakeibo login returns the friendly 503; an already
      logged-in session keeps refreshing with Mishka down.
- [ ] `grep -ri "argon2\|password_hash" apps/server` returns nothing.
- [ ] Refresh-token reuse revokes all Kakeibo sessions and leaves both siblings'
      sessions untouched.
- [ ] All three SPAs logged in simultaneously in one browser; logging out of any one
      does not log out the others (distinct localStorage keys).
- [ ] Every non-auth endpoint returns 401 without a token (scripted sweep over the
      OpenAPI route list, not a spot check).
