# Kakeibo — API Contract (external integrations + own REST surface)

Two halves: **§1–4** are the external integrations (Starling, Trading 212, Gmail,
savings-deals research) — how each is authenticated, which endpoints are used, and the
exact read-only boundary. **§5–6** is Kakeibo's own REST API, the contract between the
backend and frontend agents — do not drift from the shapes; change this doc first.

Honesty convention used throughout: anything marked **⚠️ verify** is a real-world
detail written from documentation knowledge, not from a live call with real
credentials (none exist yet — SECRETS.md). Verify each ⚠️ during that integration's
phase and correct this doc in the same commit. Nothing in this file is invented; where
certainty ends, the flag appears.

---

## 1. Starling Bank API (transactions + balances, read-only)

Starling has a genuinely good developer API — no Open-Banking aggregator middleman
(TrueLayer etc.) is needed for one's own account. Docs: <https://developer.starlingbank.com/docs>.

### 1a. Auth: Personal Access Token (not OAuth)

Full OAuth is for third-party apps with registered redirect flows. For a single person
reading their own account, Starling offers **Personal Access Tokens**: create one at
<https://developer.starlingbank.com> → sign in with the Starling account → *Personal
Access* section → create token, **ticking read-only scopes only**:

```
account:read  balance:read  transaction:read  savings-goal:read
```

**Verified at Phase 2 implementation time (2026-07-10, web search against Starling's
published scope catalogue and third-party SDKs, since developer.starlingbank.com's own
reference is a JS-rendered SPA an agent can't crawl directly):** scopes are real and
follow a `resource:verb` naming convention (`account:read`, `balance:read`,
`transaction:read`, plus much more granular ones like `account-holder-name:read`,
`customer:read`, `merchant:read` that this app doesn't need). **Correction:** the
original guess of `space:read` for reading savings Spaces **is not a real Starling
scope name** — "Spaces" is Starling's marketing name for what the API itself calls
**savings goals** (`savings-goal:read`), reached via `/api/v2/account/{accountUid}/
savings-goals` (§1b below), not a `.../spaces` path. Fine-grained account-holder
metadata scopes exist but nothing in this phase's spec needs them — `account:read`
already returns everything `get_accounts()` uses.

The token is sent as `Authorization: Bearer <PAT>`. It maps env var
**`KAKEIBO_STARLING_PAT`** (SECRETS.md). No refresh flow — PATs are long-lived and
revocable from the same portal. Sandbox (`api-sandbox.starlingbank.com` + simulator)
exists for development before the real token arrives.

### 1b. Endpoints used (base `https://api.starlingbank.com`)

```
GET /api/v2/accounts
    → {accounts:[{accountUid, defaultCategory, currency, createdAt, name}]}
      one call at first sync; persists accountUid + defaultCategory (feed queries need both)
GET /api/v2/accounts/{accountUid}/balance
    → {clearedBalance:{currency, minorUnits}, effectiveBalance:{...}, ...}
      → balance_snapshots (balance=cleared, available=effective)
GET /api/v2/feed/account/{accountUid}/category/{categoryUid}/transactions-between
        ?minTransactionTimestamp=...&maxTransactionTimestamp=...   (ISO-8601 UTC)
    → {feedItems:[{feedItemUid, categoryUid, amount:{currency, minorUnits}, direction:"IN"|"OUT",
        transactionTime, settlementTime, status, counterPartyName, reference,
        spendingCategory, source, ...}]}
GET /api/v2/account/{accountUid}/savings-goals   -- "Spaces" in the app UI; savings-goal:read
```

**Corrected at Phase 2 implementation time:** the savings endpoint is
`/api/v2/account/{accountUid}/savings-goals` (scope `savings-goal:read`), not
`/api/v2/account/{accountUid}/spaces` as originally guessed — confirmed against
Starling's public scope/endpoint naming via web search (developer.starlingbank.com's
reference itself is a JS-rendered SPA, not crawlable directly). `get_spaces()` stays
the client method name (matches PHASE-2's acceptance list and the app's own "Spaces"
terminology) but calls this real path internally. The `transactions-between` feed path
and its query params, and the `settled-transactions-between` alternative, were also
confirmed to exist against third-party SDKs referencing the real v2 API — field-level
response shape (`feedItemUid`, `amount.minorUnits`, `spendingCategory`, etc.) remains
**⚠️ unverified against a live call** (no PAT exists yet, SECRETS.md) — the fixtures in
`apps/server/tests/fixtures/starling/` model the shape as documented here; if a real
PAT reveals a field mismatch, fix the client + fixtures together, this doc third.

### 1c. Sync strategy (`integrations/starling.py` + `scripts/sync_providers.py`)

- Windowed pull: from `max(transaction_time) − 7 days` (re-fetching a week catches
  late settlements/refunds; upsert by `(account_id, provider_uid)` makes it free) to
  now. First-ever sync backfills from `KAKEIBO_STARLING_BACKFILL_START` (an optional
  local-only floor date, SECRETS.md — e.g. set it to whenever a "relevant era" starts
  for the account, never hardcoded here per PRIVATE.md's redaction scheme) or account
  creation, whichever is later, in month-sized windows. Absent that env var, the
  backfill simply starts at the account's own `createdAt`.
- Ingest normalisation: `minorUnits` + `direction` → signed `amount_minor`;
  `transactionTime` → `local_date` via Europe/London; `spendingCategory` →
  `provider_category`; then `engines/categorise.py` runs (rules → category).
- Declined/refunded items update in place (status field), never duplicate.
- Webhooks deliberately **not** used in v1 — they'd require an inbound public route to
  the tunnel; the 6-hourly pull + on-demand `POST /api/sync/run` is plenty for a
  monitoring app.
- **Read-only boundary:** the client class exposes `get_accounts / get_balance /
  get_feed / get_spaces` only. Starling's payment endpoints require scopes this PAT
  will never have — but the code discipline stands regardless (ARCHITECTURE.md §5.2).

## 2. Trading 212 API (savings-rebuild balance, read-only)

Primary integration is the exact endpoint from the brief:

```
GET https://live.trading212.com/api/v0/equity/account/summary
  → {cash: {availableToTrade, inPies, reservedForOrders},
     currency, id,
     investments: {currentValue, realizedProfitLoss, totalCost, unrealizedProfitLoss},
     totalValue}
```

- **Auth:** per T212's current public-API docs (<https://docs.trading212.com/api>):
  HTTP **Basic** — `Authorization: Basic base64(API_KEY:API_SECRET)`. The older scheme
  (`Authorization: <key>` bare — the brief's `legacyApiKeyHeader`) still appears in
  older docs (`t212public-api-docs.redoc.ly`); implement Basic (`authWithSecretKey`)
  first, fall back to the legacy header only if the live call 401s. ⚠️ verify which
  the account actually accepts on first real call.
- **Key generation** (document for the user, they do this once): Trading 212 app →
  profile menu → **Settings → API (Beta)** → generate key; select **read-only
  permissions only** (untick orders/pies write scopes if offered); copy key + secret
  immediately (secret is shown once). Env vars **`KAKEIBO_T212_API_KEY`** /
  **`KAKEIBO_T212_API_SECRET`**, plus `KAKEIBO_T212_ENV=live|demo`
  (demo base: `https://demo.trading212.com`). Stored in local `.env` only — never
  committed, never in the frontend build.
- **Rate limit:** the brief's spec says **1 request / 5 s** on this endpoint; T212's
  general docs describe burst-then-`x-ratelimit-reset` behaviour. Kakeibo's poll is
  once per sync run (6-hourly) so this never binds, but the client still sleeps 5 s
  between any two T212 calls and respects `x-ratelimit-reset` on a 429.
- **Ingest:** `totalValue`, `cash.*`, `investments.*` are floats in GBP → converted to
  pence at the client edge (`round(x*100)`), one `balance_snapshots` row per day
  (`balance = totalValue`, `available = cash.availableToTrade`, rest into
  `detail_json`).
- ⚠️ note: the public API supports **Invest and Stocks ISA** account types. If the
  rebuilt pot lives in a T212 **Cash ISA / cash-interest** product the summary shape
  may differ or be unavailable — HANDOFF Q8. Fallback if so: a `manual` account with
  quick balance entry in the UI (the goal engine only needs snapshots, not provenance).
- **Read-only boundary:** `get_account_summary()` is the *only* method. No orders, no
  pies, no history endpoints in v1.

## 3. Gmail API (rental paperwork, read-only)

### 3a. Scope — exactly one, and why

```
https://www.googleapis.com/auth/gmail.readonly
```

Gmail has no label-scoped or query-scoped OAuth grant — the choice is between
`gmail.metadata` (headers only, **no bodies or attachments** — useless here, the
attachments are the point: agent statements, interest certificates) and
`gmail.readonly`. So `gmail.readonly` it is, with the narrowing enforced **in our
code**: the pipeline only ever calls `users.messages.list` with the configured query
(§3c) and `users.messages.get`/`attachments.get` for the returned ids. No write scope,
no send, no modify, no labels API. The client class exposes `search / fetch_message /
fetch_attachment` only.

### 3b. OAuth setup (one-time, interactive — `scripts/gmail_authorise.py`)

1. Google Cloud console → new project `kakeibo-local` → enable **Gmail API**.
2. OAuth consent screen: External, add the user's own Gmail address as a test user.
3. Credentials → **OAuth client ID → Desktop app** → download `client_secret.json` →
   path in `KAKEIBO_GMAIL_CREDENTIALS_PATH` (gitignored location, SECRETS.md).
4. Run `scripts/gmail_authorise.py` in a terminal: opens a browser, user grants
   read-only access, refresh token lands at `KAKEIBO_GMAIL_TOKEN_PATH`
   (`data/secrets/gmail-token.json`, gitignored).
5. ⚠️ known Google friction, decide at implementation: apps left in **Testing**
   publishing status get refresh tokens that expire every 7 days. Options: (a) flip
   the consent screen to "In production" unverified — `gmail.readonly` is a restricted
   scope, so Google shows a scary interstitial once at grant time, then the token is
   long-lived; (b) stay in Testing and have the pipeline surface "Gmail needs
   re-authorising" via `/api/health` when the token dies. Prefer (a); verify current
   Google policy when building Phase 5.

### 3c. Pipeline (`scripts/pull_rental_emails.py`, weekly LaunchAgent)

- Query built from `tax_config` + a config list of known senders, e.g.
  `from:(agent@lettingco.example OR noreply@lender.example) OR subject:("rent" OR
  "statement" OR "mortgage interest" OR "landlord insurance") newer_than:400d`
  — the actual senders are HANDOFF Q3; until answered the query config ships empty
  and the pipeline no-ops with a `not_configured` sync_run.
- For each new message id (dedup on `tax_documents.gmail_message_id`): fetch, save
  raw `.eml` + each attachment under
  `tax-documents/<tax-year-of-received-date>/<YYYY-MM-DD>-<doc_type>-<slug>/`,
  classify `doc_type` by sender+subject keyword table (config), attempt amount parse
  (regex `£[\d,]+\.\d{2}` in body — `amount_confidence='parsed'` only on a single
  unambiguous hit), insert `tax_documents` row with `reviewed=0`.
- The UI's tax page lists unreviewed docs for a human to confirm type/amount before
  anything flows into `rental_ledger` — parsed mail never silently becomes tax data.
  **Phase 12 tightening + one narrow exception:** `doc_type='rent_statement'` is now
  assigned only to a *confirmed* letting-agent statement
  (`is_confirmed_rent_statement`: the exact `"Monthly Rental Statement "` subject
  prefix, or the configured `KAKEIBO_RENT_STATEMENT_SENDER_DOMAIN`) — not a fuzzy
  keyword match, which had swept bank/energy/broker "statement" emails into the queue.
  A confirmed statement whose PDF parses *confidently* against the learned layout is
  the single case where the pipeline auto-creates `rental_ledger` rows and sets
  `reviewed=1` itself (docs/phases/PHASE-12); every other document, and any statement
  that doesn't parse confidently, still goes through the human review gate exactly as
  before (`reviewed=0`, no ledger rows).
- Everything under `tax-documents/` is gitignored (already in the repo's `.gitignore`)
  and the folder is exactly what gets handed to an accountant at year end.

## 4. Savings-deals research (agent-assisted, not an API)

**Constraint stated plainly: there is no dependable free real-time API for UK savings
rates.** Aggregators (Moneyfacts) are commercial; scraping MoneySavingExpert/Which is
brittle and against ToS. So this feature is honest about what it is: **periodic
research with dated citations**, not a live feed.

- A scheduled task (Claude scheduled agent or a manual monthly ritual — DEPLOYMENT.md
  §4d) researches current easy-access rates across the usual sources (MSE savings
  pages, banks' own product pages) and writes `data/deals/<YYYY-MM-DD>.json`:
  ```json
  {"run_at": "2026-07-13T09:00:00Z", "method": "agent_research",
   "sources": [{"url": "https://www.moneysavingexpert.com/savings/savings-accounts-best-interest/", "fetched_at": "..."}],
   "deals": [{"provider": "...", "product": "...", "aer_pct": 4.6, "access": "easy",
              "min_deposit_minor": 0, "fscs": true, "is_isa": false,
              "source_url": "...", "notes": "includes 12-mo bonus of 0.8%"}]}
  ```
- `POST /api/deals/import` (or server startup scan of `data/deals/`) loads the newest
  file into `deal_runs`/`savings_deals`.
- **Cite-with-date discipline is a UI rule too:** every deal renders with its
  `source_url` and the run's `run_at` date; a run older than 35 days renders a "these
  rates are from <date> — likely stale" banner. The dashboard never shows a rate
  without its date.

---

## 5. Kakeibo's own REST API

Base `http://127.0.0.1:8200` (prod) / `8201` (dev), all routes under `/api`. Bearer JWT
(Kakeibo's own, AUTH.md) on everything except `login/refresh/health` and
`goal/service` (static sibling token, below). Errors
`{detail, code}`. All amounts integer pence, signed. snake_case JSON; the client never
sends user ids; POST bodies ≤64KB.

```
# Auth — identical shapes to Michi (AUTH.md)
POST /api/auth/login    {email, password} → 200 TokenPair · 401 · 429 · 503 identity_unavailable
POST /api/auth/refresh  {refresh_token}   → 200 TokenPair (rotated) · 401
POST /api/auth/logout   {refresh_token}   → 200 {logged_out: true}
GET  /api/auth/me                         → 200 {id, email, display_name, settings}

# Accounts & balances
GET  /api/accounts               → {accounts:[{id, provider, name, kind, latest_balance_minor,
                                    latest_snapshot_date, include_in_networth, status:
                                    "ok"|"not_configured"|"stale"}]}   # stale = no snapshot 48h
POST /api/accounts/manual        {name, kind, balance_minor} → 201     # manual account + snapshot
POST /api/accounts/{id}/balance  {balance_minor, local_date} → 200     # manual snapshot entry
GET  /api/networth               → {total_minor, by_account:[{account_id, name, balance_minor}],
                                    series:[{date, total_minor}] (last 90 days), as_of,
                                    emergency_fund: {months_of_cover, verdict:
                                      "unknown"|"building_from_scratch"|"below_guide"|
                                      "within_range"|"well_covered", copy},          # S2, Phase 9
                                    contractor_gap: {pension_contributing: bool|null,
                                      fte_conversion_target_date: str|null,
                                      fte_runway_goal: Goal|null}}                    # S4, Phase 9
                                    # S2/S4 fold into this bubble's detail rather than adding two
                                    # more bubbles (docs/DESIGN.md §3b row 8) — same shared function
                                    # `GET /api/summary/bubbles`'s net_worth entry also returns.

# Transactions
GET  /api/transactions?month=2026-07&category=groceries&account=1&q=tesco&page=1
     → {items:[{id, local_date, counterparty, reference, amount_minor, category:{id,key,label},
        category_source, is_rental, exclude_from_spending, settled}], total, page_size: 50}
PATCH /api/transactions/{id}     {category_id? | is_rental? | exclude_from_spending?}
     → 200 {transaction}          # sets category_source='manual'
GET  /api/categories             → {categories:[...incl viz_slot]}
GET  /api/rules · POST /api/rules · PATCH /api/rules/{id} · DELETE /api/rules/{id}
POST /api/rules/{id}/apply       → {recategorised: n}   # retro-apply, respects manual rank

# Sync
POST /api/sync/run               {providers?: ["starling","trading212"]} → 202 {run_ids}
GET  /api/sync/status            → {runs:[{provider, started_at, finished_at, status,
                                    new_rows, detail}]}   # latest per provider

# Summary & insights (§6)
GET  /api/summary/safe-to-spend  → §6a payload
GET  /api/summary/month/{yyyy-mm}?period_mode=calendar|payday → §6b payload
                                  # Phase 12 §5b: 'calendar' (default) bounds the
                                  # breakdown by the calendar month exactly as before;
                                  # 'payday' bounds it by the current payday-to-payday
                                  # window from resolve_period() — the SAME window
                                  # safe-to-spend uses for today, so the two agree.
GET  /api/tips?period=2026-07    → {tips:[{id, rule_key, severity, title, body, data}]}
POST /api/tips/{id}/dismiss      → 200
# Financial config (the safe-to-spend inputs, DATA_MODEL §5) — added Phase 4;
# §6a depends on it and PHASE-4 item 1 requires the form. Parallels /api/tax/config.
GET  /api/financial-config       → {financial_config:{payday_day, net_monthly_income_minor,
                                    flat_share_minor, buffer_minor, tax_setaside_mode,
                                    tax_setaside_fixed_minor, pension_contributing: bool|null,
                                    fte_conversion_target_date: str|null}}  # default row if none
PUT  /api/financial-config       {any subset of the above} → 200 {financial_config}
                                  # setting fte_conversion_target_date seeds/re-dates the
                                  # 'fte_runway' goal (S4, Phase 9) — target_minor stays user-set
                                  # via the ordinary PATCH /api/goals/fte_runway, never invented

# Recurring
GET  /api/recurring              → {recurring:[{id, label, cadence, typical_amount_minor,
                                    amount_drift_pct, last_seen, next_expected, occurrences,
                                    status, user_verdict, confidence, cancel_candidate: bool,
                                    monthly_equivalent_minor}], totals:{monthly_committed_minor}}
PATCH /api/recurring/{id}        {user_verdict: "keep"|"cancel_candidate"|"cancelled"|"not_recurring"} → 200
                                  # "cancelled" = a real subscription the user ended; "not_recurring" =
                                  # this was never a subscription (mortgage, savings transfer, etc.) —
                                  # both dismiss the row identically (status="dismissed"), Phase 10

# Goals
GET  /api/goals                  → {goals:[{key, label, target_minor, target_date,
                                    current_minor, baseline_minor, baseline_date,
                                    required_per_month_minor, trend_per_month_minor,
                                    projected_at_target_minor, status:
                                    "on_track"|"behind"|"no_trend",
                                    catch_up_per_month_minor, series:[{date, value_minor}]}]}
PATCH /api/goals/{key}           {monthly_pledge_minor? | target_minor? | source_account_ids?}

# Sibling read for Sukumo (its docs/API.md §4 owns the shape; static bearer token
# KAKEIBO_SERVICE_TOKEN, not the JWT flow — Sukumo never holds a household password.
# 503 service_not_configured while the token or the house_deposit goal is unconfigured;
# 401 on a missing/bad token. pct floors to one decimal (ARCHITECTURE §6); pace_status
# is the goal engine's verdict verbatim.
GET  /api/goal/service           → {goal_pence, saved_pence, pct,
                                    pace_status: "on_track"|"behind"|"no_trend", as_of}

# Tax (TAX.md governs the semantics)
GET  /api/tax/config · PUT /api/tax/config        # the HANDOFF open-question inputs, incl. Phase 10's
                                    # mortgage_rate_pct/mortgage_balance_minor (an honest fallback for
                                    # annual_mortgage_interest_minor when the certificate figure is
                                    # unknown — balance is OUTSTANDING, not the original loan; the
                                    # certificate figure always wins when both are set)
GET  /api/tax/years/{key}/summary → {gross_rents_minor, allowable_expenses:{<type>: minor,...},
                                    profit_minor, estimate: null | {method_used:
                                    "expenses_plus_s24"|"property_allowance",
                                    tax_due_minor, s24_credit_minor, comparison:{...},
                                    marginal_band, assumptions:[str], disclaimer: str},
                                    missing_inputs:[str]}   # estimate null while inputs missing;
                                    # assumptions carries a note when mortgage interest is a
                                    # rate×balance estimate rather than the exact certificate figure
GET  /api/tax/documents?year=2026-27&unreviewed=1 → {documents:[{...,
                                    ledger_entry_count}]}   # Phase 12: how many
                                    # rental_ledger rows this document produced —
                                    # >0 = auto-processed into the ledger (a confirmed
                                    # rent statement parsed by the Phase-12 pipeline, or
                                    # a human), so the review UI shows "in ledger" not a
                                    # review action (docs/phases/PHASE-12 item 1e)
PATCH /api/tax/documents/{id}    {doc_type? | amount_minor? | reviewed?} → 200
POST /api/tax/ledger             {tax_year, local_date, kind, expense_type?, amount_minor,
                                  transaction_id? | tax_document_id?, notes?} → 201
GET  /api/tax/ledger?year=2026-27 · DELETE /api/tax/ledger/{id}

# Deals
GET  /api/deals                  → {run: {run_at, sources:[...]} | null, deals:[...], stale: bool}
POST /api/deals/import           → 200 {imported: n}   # loads newest data/deals/*.json

# Personal wants (goal 11, Phase 9) — the affordability check is computed live per
# unbought item, never stored (docs/DATA_MODEL.md §7a-i)
GET  /api/wants                  → {wants:[{id, label, price_minor, bought, created_at,
                                    affordability: {verdict, detail} | null}]}  # null once bought
POST /api/wants                  {label, price_minor} → 201 {want}
PATCH /api/wants/{id}            {label? | price_minor? | bought?} → 200 {want}
DELETE /api/wants/{id}           → 200 {deleted: true}

# Gift-occasion budgets (goal 10, Phase 9) — shares the affordability mechanic via its
# own endpoint rather than duplicating it (docs/DATA_MODEL.md §7a-i)
GET  /api/gifts/occasions        → {occasions:[{id, label, limit_minor, target_date,
                                    items:[{id, occasion_id, label, price_minor, bought,
                                    bought_date}], spent_minor, remaining_minor,
                                    verdict: "no_limit_set"|"under_limit"|"over_limit"}]}
POST /api/gifts/occasions        {label, limit_minor?, target_date?} → 201 {occasion}
PATCH /api/gifts/occasions/{id}  {label? | limit_minor? | target_date?} → 200 {occasion}
DELETE /api/gifts/occasions/{id} → 200 {deleted: true}   # cascades its items
POST /api/gifts/occasions/{id}/items  {label, price_minor} → 201 {occasion}
PATCH /api/gifts/items/{id}      {label? | price_minor? | bought? | bought_date?} → 200 {occasion}
DELETE /api/gifts/items/{id}     → 200 {deleted: true}
GET  /api/gifts/items/{id}/affordability → {verdict, detail}  # vs the occasion's remaining budget

# Splits (only if PLAN §4 S3 accepted)
GET  /api/splits · POST /api/splits · PATCH /api/splits/{id} · POST /api/splits/settle
GET  /api/splits/balance         → {net_minor, direction: "they_owe"|"i_owe"|"even"}

# Health
GET  /api/health → {status:"ok", identity:"reachable"|"unreachable",
                    integrations:{starling:"ok"|"not_configured"|"error"|"stale",
                                  trading212:..., gmail:...},
                    last_sync:{starling: ts|null, ...}}    # flags only, never balances
```

## 6. Engine contracts (the numbers behind §5)

### 6a. Safe-to-spend (goal 1) — `GET /api/summary/safe-to-spend`

Month = payday-anchored. The period comes from `financial_config.payday_day` when set
manually; **otherwise (Phase 11) from a detected salary anchor's own transaction
history** — `period_start` = the most recent detected salary date, `period_end` =
`+ median(observed gaps) − 1`, rolled forward by the median gap if `today` has already
passed it. This represents "last Friday of the month" (a different day-of-month each
month) that the literal 1–31 `payday_day` cannot. All figures pence:

```
income        = net_monthly_income (config) + confirmed rental income landing this period
committed     = Σ active recurring_payments (monthly_equivalent) + flat_share (config)
                  [dedup: a recurring row matching flat_share counts once]
                  -- Phase 4 note: financial_config has no flat_share counterparty
                     field to match on, so the dedup matches on AMOUNT instead — an
                     active recurring monthly-equivalent within ±12%/±£1.50 of
                     flat_share_minor is treated as already representing it. A
                     *confident* match only: when unsure we do NOT suppress, since
                     double-counting is conservative (understates safe-to-spend)
                     whereas wrongly suppressing would flatter the user (§6/ARCH §6).
goal_set_aside= Σ goals.monthly_pledge (or required_per_month where pledged=NULL and status≠no_trend,
                  house_deposit only — rebuild rides on whatever's left unless pledged)
tax_set_aside = per financial_config.tax_setaside_mode ('auto' = current-year estimated
                  SA liability ÷ months to next 31 Jan; 0 while tax inputs incomplete)
                  -- Phase 4 note: the safe_to_spend() engine takes the annual SA
                     estimate as an input and, in 'auto' mode, sets aside
                     ceil(estimate ÷ months_to_next_31_jan). Phase 4 passes None (tax
                     inputs incomplete ⇒ 0); Phase 5's estimator feeds the real figure
                     in once its inputs land, with no engine change.
buffer        = financial_config.buffer_minor
safe_to_spend = income − committed − goal_set_aside − tax_set_aside − buffer
```

Response: every line above (so the UI can show the waterfall, DESIGN.md §4a), plus
`spent_so_far_minor` (discretionary categories this period), `remaining_minor`,
`per_day_remaining_minor` (remaining ÷ days left, floor), `period:{start, end}`, and
`setup_missing:[...]` — payday/income neither set manually **nor confidently detected**
⇒ the endpoint returns the setup list instead of pretending (`safe_to_spend: null`).

**Provenance (Phase 11)** — the response also carries, per field:
`payday_source` / `net_income_source` ∈ `'manual' | 'detected' | null`. **Manual always
wins**: an explicitly set `payday_day` / `net_monthly_income_minor` is used exactly as
before and reported `'manual'`; a detection only fills a field the user left unset and
is reported `'detected'`. When a detected source is used, `detected_income` carries the
human-readable why — `{label, typical_amount_minor, cadence, median_gap_days,
occurrences, confidence, last_seen}` — so the UI can say "worked out from a recurring
payment from X averaging £Y, roughly every N days" and offer an override, never presenting
an inferred figure as if typed in. `detected_income` is `null` when both fields are
manual or still in setup. **No schema change**: this is pure computation over the
already-synced `transactions` — `financial_config` gains no columns. The income anchor
is the single largest **monthly** incoming recurring pattern at/above the confidence
floor (salary), detected by the same `engines/recurring.py` machinery as outgoings via
its long-present `direction="in"` path.

### 6b. Monthly breakdown + verdicts (goal 5) — `GET /api/summary/month/{yyyy-mm}`

```
{month, income_minor, spend_minor, net_minor,
 categories:[{key, label, viz_slot, spend_minor, share_pct, avg_3mo_minor,
              delta_vs_avg_pct, benchmark: null | {band: "maintainable"|"average"|"above_average",
              band_bounds_minor:[lo, hi], source: str, as_of: str}}],
 largest_movers:[{key, delta_minor}], methodology_note: str,
 # Phase 12 §5b provenance — always present, additive (calendar-mode numbers are
 # unchanged from before the toggle; these just say how the window was chosen):
 period_mode: "calendar"|"payday",
 period: {start, end},              # calendar-month bounds, or the payday window;
                                    # {null,null} when payday mode can't resolve a period
 payday_source: "manual"|"detected"|null,   # non-null only in payday mode
 setup_missing: [str]}              # payday mode with no resolvable period → e.g.
                                    # ["payday_day"], categories empty (degrade, not crash)
```

In `'payday'` mode the trailing-3 comparison uses the three preceding equal-length
payday windows (apples-to-apples with the current window), mirroring calendar
mode's this-3-months / prev-3-months; benchmark bands (monthly figures) apply as-is
since a payday window is ~one month.

**Benchmark methodology — heuristic, stated as such (the `methodology_note` ships in
every response):** bands per category live in a config file
(`apps/server/app/engines/benchmarks.py`) seeded loosely from ONS Family Spending
(living-costs and food survey) figures for a two-adult, no-children household,
adjusted to Scotland and a young-professional profile, each entry carrying its source
URL and as-of date. They are **approximate comparison bands, not statistical truth**
— the UI copy says "roughly typical" and the verdict pill is `worth_a_look`-toned,
never alarmed. Verdict = trailing-3-month average vs band (single odd months don't
flip verdicts). ⚠️ the initial band values are set at Phase-4 time from the then-latest
ONS release, cited in the config file itself.

### 6c. Tips rules (goal 6) — regenerated on sync for the current period

| rule_key | Fires when | Tone guard |
|---|---|---|
| `category_trending_up` | category's 3-mo avg ≥ 20% over its previous 3-mo avg, and ≥ £30/mo absolute | states both numbers; suggests a look, not a cut |
| `cancel_candidate` | recurring row flagged per DATA_MODEL §3a.4 | "worth checking you still use this" |
| `price_rise` | recurring `amount_drift_pct` ≥ 10% | names old vs new amount |
| `discretionary_variance` | stdev of last 6 months' discretionary spend > 35% of its mean | frames as predictability for safe-to-spend, not overspending |
| `emergency_fund_low` | accessible cash < 3 × essential monthly spend (S2 accepted) | explicitly acknowledges the deposit-first trade-off |
| `tax_setaside_gap` | tax estimate exists and set-aside mode 'off' (S5 accepted) | informational |
| `sa_registration_deadline` | `tax_config.registered_for_sa` is NULL or 0 and today ∈ [1 Jul, 5 Oct] of a year following a rental tax year | the one tip allowed to be insistent — a real statutory deadline (TAX.md §6) |

Rules are pure functions in `engines/insights.py`, each unit-tested with a fixture
month. No LLM calls anywhere in the tips path — every sentence is a template with
numbers filled in, so nothing can hallucinate financial advice.
