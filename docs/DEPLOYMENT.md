# Kakeibo — Deployment & Operations

The runbook for putting Kakeibo in production and keeping it there. Topology is
identical to the siblings' (Mishka Hub `docs/DEPLOYMENT.md` is the long-form original;
Michi's ARCHITECTURE §5b is the tested compact form): **GitHub Pages SPA + loopback
uvicorn behind the shared Cloudflare Tunnel + LaunchAgents on the household Mac.**
This doc only spells out Kakeibo's values and the deltas; the gotchas below were paid
for by the siblings — do not re-pay them.

## 0. The numbers

| Thing | Value |
|---|---|
| Web (Pages) | `https://fyreline.github.io/Finances/` (repo `Fyreline/Finances`, public) |
| API prod | LaunchAgent `com.kakeibo.api`, uvicorn `127.0.0.1:8200`, serves `data/kakeibo.db`, **no `--reload`** |
| API dev | launch.json entry `kakeibo-api`, port `8201`, `KAKEIBO_DATABASE_URL` → `data/kakeibo.dev.db` |
| Web dev | launch.json entry `kakeibo-web`, port `5178` |
| Tunnel hostname | `kakeibo-api.mishka-hub.com` → `http://127.0.0.1:8200` |
| Logs | `~/Library/Logs/kakeibo/` |

## 1. Frontend → GitHub Pages

Copy Michi's `.github/workflows/deploy-pages.yml` and adapt: trigger on push to `main`
touching `apps/web/**`; build with `VITE_BASE=/Finances/` and repo variable
`VITE_API_BASE=https://kakeibo-api.mishka-hub.com`; `index.html` → `404.html`
SPA-fallback copy; official Pages actions. One-time manual repo setup mirrors Mishka's
§1a: Settings → Pages → Source: GitHub Actions; add the `VITE_API_BASE` variable.

**Public-repo audit is a launch gate, not a nicety** (this is the finance app):
before the first push to a public remote, run the phase-8 secret/personal-data sweep —
grep full git history for key fragments, `£` amounts in fixtures, the user's email,
and check `dist/` output. `.gitignore` already fences `data/`, `tax-documents/`,
`.env*` (except `.env.example`), `.secrets/`, `credentials/`.

## 2. Tunnel ingress (shared household tunnel — edit with care)

The tunnel is a **root LaunchDaemon** shared by all three apps; its config is
`~/.cloudflared/config.yml`. Add the Kakeibo hostname **above** the catch-all 404
rule, alongside the existing entries:

```yaml
  - hostname: kakeibo-api.mishka-hub.com
    service: http://127.0.0.1:8200
```

Then: `cloudflared tunnel route dns <tunnel-name> kakeibo-api.mishka-hub.com` (creates
the CNAME) and restart the daemon — root daemon, so:

```bash
sudo launchctl kickstart -k system/com.cloudflare.cloudflared
```

Verify `https://kakeibo-api.mishka-hub.com/api/health` from a phone on mobile data,
and that the **siblings still answer** (`michi-api.…/api/health`, Mishka's hostname) —
a broken shared config takes down all three apps, which is the real risk of this step.

## 3. API LaunchAgent

`~/Library/LaunchAgents/com.kakeibo.api.plist` — **ready-made templates for all four
agents live in `deploy/launchagents/` (prepared in Phase 8, modelled byte-for-byte on
Michi's installed plists)** — copy from there rather than re-deriving from
`com.michi.api` (WorkingDirectory `…/Finances/apps/server`, `.venv/bin/uvicorn
app.main:app --host 127.0.0.1 --port 8200`, logs `~/Library/Logs/kakeibo/`).

```bash
mkdir -p ~/Library/Logs/kakeibo
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kakeibo.api.plist
launchctl kickstart -k gui/$(id -u)/com.kakeibo.api     # restart after deploys
```

Pre-paid gotchas that WILL bite here otherwise:

1. **TCC / Documents access:** launchd-spawned processes can't read
   `~/Documents/**` until the *actual python binary* (resolve the venv symlink) has
   Full Disk Access — Mishka gotcha #2. The same grant likely already exists from the
   siblings if the same Python version builds this venv; verify before assuming.
2. **Any LaunchAgent touching `~/Documents` must invoke `.venv/bin/python`
   directly, never `/bin/sh` scripts** — Michi's backup agent failed silently under
   `/bin/sh` (per-app Files & Folders permission attaches to the binary). All four
   Kakeibo agents follow this rule.
3. Editing a `.py` does nothing on 8200 until you `kickstart` it (no `--reload` in
   prod — by design).

## 4. The scheduled agents (all `.venv/bin/python`, per gotcha 2)

| Agent | Schedule | Runs | Notes |
|---|---|---|---|
| `com.kakeibo.sync` | every 6 h (`StartInterval` 21600) | `scripts/sync_providers.py` | Starling + T212 pull → SQLite. Exits 0 with a `not_configured` sync_run while keys are absent — safe to install before credentials exist. |
| `com.kakeibo.gmail` | weekly (`StartCalendarInterval` Sun 09:00) | `scripts/pull_rental_emails.py` | no-ops until the Gmail token + sender config exist (API.md §3c). |
| `com.kakeibo.backup` | daily 03:15 | `scripts/backup_db.py` | port of Michi's: sqlite3 `.backup()` API (WAL-safe — never `cp` a live db) → `data/backups/kakeibo-<ts>.db`, prune to 30. **Also backs up `tax-documents/`** (tar.gz alongside, prune to 8 weekly) — that folder is real paperwork, not re-derivable if Gmail messages get deleted. |
| `com.kakeibo.api` | KeepAlive | uvicorn | §3 |

Michi's 3am slot is taken by its own backup; 03:15 avoids two sqlite backups
contending for disk at the same second. Off-machine copy of `data/backups/` remains
the user's standing decision (same note as Mishka §4) — **for this app push on it**:
bank history + tax paperwork on one failing disk is a genuinely bad day.

### 4d. Savings-deals research schedule

Not a LaunchAgent — it needs judgement, not cron: a **Claude scheduled task** (or a
monthly human-triggered skill) that researches current UK easy-access rates and writes
`data/deals/<date>.json` per API.md §4, citing source URLs + fetch dates. Set it up in
Phase 6 with a monthly cadence; the dashboard's staleness banner (>35 days) is the
watchdog if a run is missed.

**Concrete setup, once a household member has a moment (Phase 6 built the mechanism —
data shape, import endpoint, seeded placeholder, UI — but could not create a live
scheduled task itself: a coding-phase agent has no web-search tool in that context, and
inventing rates would violate the "never a guessed number" rule that runs through this
whole app):**

1. **Preferred — a monthly Claude scheduled task.** Use the `schedule` skill (or the
   `mcp__scheduled-tasks__*` tools directly) to create a routine, cadence "monthly",
   whose prompt is: *"Read `apps/server/scripts/research_deals_prompt.md` in the
   Finances repo and follow it exactly: research current UK easy-access savings rates,
   then write the resulting `data/deals/<YYYY-MM-DD>.json` file into that repo. After
   writing it, `curl -X POST` the dev or prod `/api/deals/import` endpoint (whichever is
   running) so the new run shows up without waiting for a restart."* The task needs
   read/write filesystem access to the repo and a live web-search tool — run it as a
   normal (non-sandboxed) Claude session on the household Mac, not inside the API's own
   process.
2. **Fallback — a manual monthly ritual.** If nobody wants a standing scheduled task:
   once a month, open a Claude Code session in this repo and say "run the deals
   research" (or open `scripts/research_deals_prompt.md` directly and work through it by
   hand using MSE + the providers' own pages). Either way produces the same
   `data/deals/<date>.json` shape — the app doesn't know or care which path produced it.
3. **First real run:** the moment either path above produces its first genuine,
   source-cited file, it becomes the newest run and permanently supersedes the
   synthetic placeholder Phase 6 seeded at first boot (`app/seed_deals.py` — labelled
   "SYNTHETIC TEST DATA" throughout, never presented as a real rate). No code change
   needed; `newest_deal_run_file()` just starts picking the new, later-dated file.

## 5. CORS & env

`https://fyreline.github.io` ships in `config.py`'s default `cors_origins` (plus the
two localhost:5178 dev origins), same as the siblings — nothing to set for the plain
Pages URL. Server env checklist lives in [SECRETS.md](SECRETS.md); the minimal boot set
is `KAKEIBO_JWT_SECRET` only (everything else degrades to `not_configured`).

## 6. Acceptance criteria

- [ ] Push to `main` auto-deploys the SPA; loads at the Pages URL with correct asset
      paths; login round-trips through the tunnel from a non-household network.
- [ ] `kakeibo-api.mishka-hub.com/api/health` serves over HTTPS from mobile data; both
      sibling APIs still healthy after the ingress edit.
- [ ] Mac reboot → cloudflared, `com.kakeibo.api`, and all three scheduled agents come
      back without human action.
- [ ] `curl http://<mac-lan-ip>:8200` from another device fails (loopback binding
      proven).
- [ ] Nightly backup produces dated db + tax-documents archives; restore drill
      performed once and timed (document the duration here afterwards).
- [ ] Public-repo audit (§1) passed before first push; `dist/` contains no key
      fragments, no personal data, no baked balances.
- [ ] Sync agent runs green with real keys; `sync_runs` rows show `ok` with plausible
      `new_rows`; dashboard sync pill reflects it.
