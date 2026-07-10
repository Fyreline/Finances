# Phase 8 — Verify & ship (owner: Fable)

The gauntlet, then production. Nothing here is new work; it is proving the docs'
promises against the running system — **observed live, not reported** (the household's
standing subagent lesson).

## 1. The gauntlet (all against 8201/dev db unless stated)

- [ ] Every phase doc's acceptance list re-run end-to-end in one sitting; any red box
      is a stop.
- [ ] Full test suite: pytest + typecheck + vitest, output pasted.
- [ ] AUTH.md §4 criteria including the three-SPA localStorage isolation and the
      401-sweep over the OpenAPI route list.
- [ ] Read-only audit: `grep -rn "\.post\|\.put\|\.delete" app/integrations/` clean
      (OAuth token exchange in gmail.py is the sole permitted hit); provider
      credentials confirmed read-only-scoped at each provider's portal (human does
      this — record it in HANDOFF).
- [ ] Trust-boundary audit: build `dist/`, grep for env values, key fragments,
      email addresses, any `£` figure; grep **full git history** before the repo
      goes/stays public (DEPLOYMENT §1).
- [ ] Tax engine: TAX.md §7 boxes re-verified; then a human sanity-check of one
      year's estimate against HMRC's online calculator with the same inputs
      (record the delta — should be £0 or explained).
- [ ] Fixture-mode walkthrough: with NO credentials in .env, every bubble shows its
      setup state and nothing crashes (`/api/health` all `not_configured`).

## 2. Ship (DEPLOYMENT.md top to bottom)

- [ ] venv + LaunchAgents installed (`api`, `sync`, `gmail`, `backup`); TCC/Full-Disk
      granted to the venv's python binary; reboot test — everything returns.
- [ ] Tunnel ingress added, `sudo launchctl kickstart -k
      system/com.cloudflare.cloudflared`, all THREE apps' health endpoints verified
      from mobile data.
- [ ] Pages workflow live, `VITE_API_BASE` variable set, real login from the public
      URL on a phone.
- [ ] Backup ran once for real; restore drill performed and timed into
      DEPLOYMENT.md §6.
- [ ] Real credentials (as supplied by then — SECRETS.md): pasted into `.env`,
      kickstart, `POST /api/sync/run`, real balances appear; if any credential is
      still pending, its bubble's setup state is the accepted ship condition, noted
      in HANDOFF.

## 3. Handoff hygiene

- [ ] HANDOFF.md updated: what shipped, open questions still open, the "left for
      humans" list (credential creation, accountant sanity-check, off-machine backup
      decision).
- [ ] CLAUDE.md written for this repo (commands, hard rules — no-write-scopes,
      pence-only, docs-win — and the gotchas actually paid for during
      implementation).
- [ ] README.md: one screenshot, one paragraph, pointer to docs/.
