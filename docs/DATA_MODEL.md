# Kakeibo — Data Model (SQLite `data/kakeibo.db`)

SQLAlchemy 2.x mapped classes in `app/models.py`; timestamps UTC
`"%Y-%m-%d %H:%M:%S"` strings (household convention); **all money columns are integer
pence, signed from the user's perspective (negative = out), names ending `_minor`**
(ARCHITECTURE.md §6). Provider ids are stored verbatim as TEXT and are the idempotency
keys for sync — a re-run must never duplicate a row.

## 1. Identity & infrastructure (ports from Michi)

```sql
users                                    -- AUTH.md; Mishka Hub is the credential store
  id INTEGER PK
  email TEXT UNIQUE NOT NULL             -- lower()
  display_name TEXT NOT NULL             -- refreshed from Mishka at every login
  mishka_user_id INTEGER NOT NULL
  created_at TEXT NOT NULL
  settings_json TEXT NOT NULL DEFAULT '{}'
      -- {theme handled client-side; dashboard_tiles_order: [...],
      --  hidden_suggestions: ["S4", ...]}

refresh_tokens                           -- line-for-line port of Michi's
  id INTEGER PK
  user_id INTEGER NOT NULL REFERENCES users(id)
  token_hash TEXT UNIQUE NOT NULL
  expires_at TEXT NOT NULL
  revoked INTEGER NOT NULL DEFAULT 0
  created_at TEXT NOT NULL
```

Kakeibo is effectively single-user, but rows still key on `user_id` so the household
pattern holds and nothing leaks if the primary user's partner ever logs in with her
Mishka identity: **she would see an empty Kakeibo, not his** — every query filters on
`user_id`, and provider credentials attach to accounts owned by the primary user's row.

## 2. Accounts, balances, transactions

```sql
accounts
  id INTEGER PK
  user_id INTEGER NOT NULL REFERENCES users(id)
  provider TEXT NOT NULL                 -- 'starling' | 'trading212' | 'manual'
  provider_account_uid TEXT              -- Starling accountUid / T212 id; NULL for manual
  name TEXT NOT NULL                     -- "Starling current", "T212 Invest", ...
  kind TEXT NOT NULL                     -- 'current' | 'savings' | 'investment'
  currency TEXT NOT NULL DEFAULT 'GBP'
  default_category_uid TEXT              -- Starling's defaultCategory (feed queries need it)
  include_in_networth INTEGER NOT NULL DEFAULT 1
  created_at TEXT NOT NULL
  UNIQUE (provider, provider_account_uid)

balance_snapshots                        -- one row per account per capture; goals + net worth
  id INTEGER PK
  account_id INTEGER NOT NULL REFERENCES accounts(id)
  captured_at TEXT NOT NULL
  local_date TEXT NOT NULL               -- Europe/London date of capture; the trend axis
  balance_minor INTEGER NOT NULL         -- cleared/total value
  available_minor INTEGER                -- Starling effective / T212 cash.availableToTrade
  detail_json TEXT                       -- T212: {inPies, investments:{...}} etc. server-side only
  UNIQUE (account_id, local_date)        -- one snapshot a day; re-sync updates in place

transactions
  id INTEGER PK
  account_id INTEGER NOT NULL REFERENCES accounts(id)
  provider_uid TEXT NOT NULL             -- Starling feedItemUid
  amount_minor INTEGER NOT NULL          -- signed (negative = out)
  transaction_time TEXT NOT NULL         -- provider timestamp, UTC
  local_date TEXT NOT NULL               -- Europe/London date — ALL month grouping uses this
  settled INTEGER NOT NULL DEFAULT 0
  counterparty TEXT                      -- counterPartyName
  reference TEXT
  provider_category TEXT                 -- Starling spendingCategory (e.g. GROCERIES)
  category_id INTEGER REFERENCES categories(id)   -- Kakeibo's own; NULL = uncategorised
  category_source TEXT NOT NULL DEFAULT 'provider' -- 'provider' | 'rule' | 'manual'
  is_rental INTEGER NOT NULL DEFAULT 0   -- feeds the tax ledger (§6)
  exclude_from_spending INTEGER NOT NULL DEFAULT 0 -- transfers-to-self, one-offs user excludes
  raw_json TEXT NOT NULL                 -- full provider payload; never sent to the SPA
  UNIQUE (account_id, provider_uid)
  INDEX (account_id, local_date)
  INDEX (category_id, local_date)

sync_runs                                -- observability for the sync LaunchAgent
  id INTEGER PK
  provider TEXT NOT NULL
  started_at TEXT NOT NULL
  finished_at TEXT
  status TEXT NOT NULL                   -- 'ok' | 'error' | 'not_configured'
  new_rows INTEGER NOT NULL DEFAULT 0
  detail TEXT                            -- error message / rate-limit note
```

`category_source` ordering matters: a `manual` assignment is never overwritten by a
re-sync or a rule change; `rule` beats `provider`; re-running categorisation only
touches rows whose source is below the assigner's rank.

## 3. Categories, rules, recurring payments

```sql
categories
  id INTEGER PK
  key TEXT UNIQUE NOT NULL          -- 'groceries', 'eating_out', 'transport', 'subscriptions',
                                    -- 'housing', 'bills', 'fun', 'holidays', 'gifts', 'health',
                                    -- 'salary', 'rental_income', 'rental_expense',
                                    -- 'savings_transfer', 'transfer_self', 'other'
  label TEXT NOT NULL               -- display, British English ("Eating out")
  kind TEXT NOT NULL                -- 'income' | 'fixed' | 'discretionary' | 'rental' | 'transfer'
  viz_slot INTEGER                  -- stable 1..8 → --color-viz-N (DESIGN.md §2b); colours never reshuffle
  sort INTEGER NOT NULL DEFAULT 0

category_rules                      -- ordered first-match-wins; editable in the UI
  id INTEGER PK
  priority INTEGER NOT NULL
  match_field TEXT NOT NULL         -- 'counterparty' | 'reference' | 'provider_category'
  pattern TEXT NOT NULL             -- case-insensitive substring or /regex/
  category_id INTEGER NOT NULL REFERENCES categories(id)
  set_is_rental INTEGER NOT NULL DEFAULT 0   -- e.g. letting-agent payout rule
  set_exclude INTEGER NOT NULL DEFAULT 0     -- e.g. transfers to own T212
  created_at TEXT NOT NULL

recurring_payments
  id INTEGER PK
  user_id INTEGER NOT NULL REFERENCES users(id)
  merchant_key TEXT NOT NULL        -- normalised counterparty (lower, stripped of store numbers)
  label TEXT NOT NULL
  category_id INTEGER REFERENCES categories(id)
  cadence TEXT NOT NULL             -- 'monthly' | 'weekly' | 'quarterly' | 'annual'
  typical_amount_minor INTEGER NOT NULL   -- median of matched amounts
  amount_drift_pct REAL NOT NULL DEFAULT 0 -- max deviation seen; price rises surface here
  first_seen TEXT NOT NULL
  last_seen TEXT NOT NULL
  next_expected TEXT                -- last_seen + cadence
  occurrences INTEGER NOT NULL
  status TEXT NOT NULL DEFAULT 'active'    -- 'active' | 'lapsed' (missed 2 cycles) | 'dismissed'
  user_verdict TEXT                 -- NULL | 'keep' | 'cancel_candidate' | 'cancelled' | 'not_recurring'
  confidence REAL NOT NULL          -- 0..1 (§3a)
  UNIQUE (user_id, merchant_key, cadence)
```

### 3a. Recurring detection algorithm (`engines/recurring.py`)

Runs after every sync over outgoing, non-excluded transactions.

> **Correction (Phase 4 implementation):** the original "trailing 13 months"
> was internally inconsistent with this section's own ≥3-occurrence rule (step
> 2) at the **annual** cadence (350–380 day gaps) — three annual occurrences
> cannot fit inside 13 months. Resolved by splitting the one window into two:
> occurrences are **gathered** over a window wide enough to satisfy every
> cadence's ≥3 rule (≈38 months / 3 years), and **13 months is kept as a
> recency filter on `last_seen`** — so a still-live annual insurance (last
> paid this month, first paid two years ago) surfaces, while a monthly sub
> cancelled 18 months ago does not. Behaviour for the common monthly case is
> unchanged.

1. **Group** by `merchant_key` = `counterparty` lowercased, digits/branch suffixes
   stripped (`"TESCO STORES 3412"` → `"tesco stores"`), then within a group by amount
   cluster: amounts within **±12% or ±£1.50** (whichever is larger) of the running
   median join the cluster. (Groceries at Tesco won't cluster — amounts vary too much;
   a £9.99 subscription will.) *Note (Phase 4): a price rise larger than the
   clustering tolerance (>±12% AND >±£1.50) splits into two clusters, so only
   rises within tolerance surface via `amount_drift_pct` — an inherent
   consequence of this tolerance rule, not a bug.*
2. **Cadence test** per cluster with ≥3 occurrences: median gap between consecutive
   dates → monthly if 28–33 days, weekly 6–8, quarterly 85–97, annual 350–380; and no
   gap may exceed 1.6× the median (one missed month tolerated in 12).
3. **Confidence** = `0.4·min(occurrences,6)/6 + 0.3·(1 − gap_variance_norm) +
   0.3·(1 − amount_spread_norm)`, floor at 0.35 to surface at all; the UI orders by it
   and labels < 0.6 as "possibly recurring".
4. **Cancel-candidate flag** (goal 7): heuristic, advisory only — flagged when
   `category ∈ {subscriptions, fun, other}` AND tenure ≥ 4 months AND
   `typical_amount_minor ≤ £25` AND the merchant has no non-recurring transactions in
   90 days (no top-ups/extras suggests no active engagement). Kakeibo cannot know
   actual usage of a Netflix account — the copy must say "worth checking you still use
   this", never "unused".
5. Upserts preserve `user_verdict`; a dismissed row stays dismissed. `'cancelled'` and
   `'not_recurring'` (Phase 10) both set `status='dismissed'` identically — the
   distinction is purely an honest label for *why* the user dismissed it: `'cancelled'`
   is a real subscription they ended (Netflix, gym); `'not_recurring'` is the detector
   flagging something that was never a subscription to begin with (a mortgage standing
   order, a Starling Space transfer to savings) — wrong framing to call "cancelled"
   since it's still active, just never was a subscription.

Salary and rent arriving are detected the same way on **incoming** transactions
(cadence monthly, amount stable) and offered as the income anchors for safe-to-spend
(API.md §6a) rather than auto-assumed.

## 4. Goals & projections

```sql
goals
  id INTEGER PK
  user_id INTEGER NOT NULL REFERENCES users(id)
  key TEXT UNIQUE NOT NULL          -- 'house_deposit' | 't212_rebuild' | 'emergency_fund'
                                    -- | 'fte_runway' (S4, Phase 9 — seeded once
                                    --   financial_config.fte_conversion_target_date is set)
  label TEXT NOT NULL
  target_minor INTEGER              -- house_deposit: user-configured (PRIVATE.md); NULL = open-ended (t212_rebuild)
  target_date TEXT                  -- house_deposit: user-configured exact date, per the brief
  baseline_minor INTEGER NOT NULL   -- t212_rebuild/house_deposit: user-configured low baseline
  baseline_date TEXT NOT NULL       -- baseline snapshot date (PRIVATE.md has the real value)
  source_account_ids TEXT NOT NULL  -- JSON list; balance = Σ snapshots of these accounts
  monthly_pledge_minor INTEGER      -- user-set intention; NULL = derived requirement only
  created_at TEXT NOT NULL
```

No `goal_contributions` table — contributions are **derived** from
`balance_snapshots` deltas (month-end value minus previous month-end) so manual
top-ups, interest, and market movement all count without double bookkeeping. Market
noise caveat for T212-backed goals: the monthly delta conflates contributions with
investment gains/losses; the UI labels the series "balance growth", not
"contributions" (DESIGN.md §4c).

### 4a. Projection maths (`engines/goals.py`, pure functions)

For a goal with target `T`, target date `D`, current balance `B` (latest snapshot sum),
evaluated on date `t`:

```
months_remaining  m = count of month-ends in (t, D]          # e.g. t=2026-07-10, D=2027-01-10 → 6
required_per_month = ceil((T − B) / m)                       # ceil: never flatter (ARCH §6)
trend_per_month    = median of last 3 month-end deltas       # median: one odd month can't lie
projected_at_D     = B + trend_per_month · m
status: 'on_track'  if projected_at_D ≥ T
        'behind'    otherwise → catch_up = ceil((T − B) / m) # surfaced as "would need £X/month"
        'no_trend'  if < 2 month-end snapshots exist yet
```

Worked example pinned as a unit test using generic placeholder figures — substitute the
real `T`/`B`/`t`/`D` from PRIVATE.md when writing the actual test fixture, never commit
the real numbers into the test file itself (load them from local config/env at test
time): `T=£10,000, B=£1,000, t=2026-07-10, D=2027-01-10` → `m=6`,
`required_per_month = ceil(9000/6) = £1,500`. The dashboard's first render should show
the equivalent computed figure for the real, locally-configured goal.

`emergency_fund` has no fixed target: its target is computed as
`3 × essential_monthly_spend` (trailing-3-month average of `kind='fixed'` +
groceries), verdict bands 3–6 months per PLAN §4 S2.

## 5. User financial config (DB, not env — ARCHITECTURE.md §4)

```sql
financial_config                    -- single row per user; the safe-to-spend inputs
  user_id INTEGER PK REFERENCES users(id)
  payday_day INTEGER                -- e.g. 28; NULL until confirmed (HANDOFF Q5)
  net_monthly_income_minor INTEGER  -- take-home; NULL until confirmed → safe-to-spend shows setup card
  flat_share_minor INTEGER          -- monthly payment for the flat (HANDOFF Q6)
  buffer_minor INTEGER NOT NULL DEFAULT 15000   -- £150 monthly slack, user-tunable
  tax_setaside_mode TEXT NOT NULL DEFAULT 'auto' -- 'auto' (from tax estimate ÷ months) | 'fixed' | 'off'
  tax_setaside_fixed_minor INTEGER
  pension_contributing INTEGER      -- S4 (PLAN §4 S4, PHASE-9 §3); NULL=unanswered, 0/1 — NEVER
                                     --   defaulted to 0, an unconfirmed pension gets asked, not assumed
  fte_conversion_target_date TEXT   -- S4; NULL until set. Once set, seeds/re-dates the 'fte_runway'
                                     --   goal row below (target_minor stays user-set, never invented)
  updated_at TEXT NOT NULL

tax_config                          -- TAX.md §2 inputs; NULLs = unanswered open questions.
  user_id INTEGER PK REFERENCES users(id)       --   The estimator REFUSES to produce a headline
  monthly_rent_minor INTEGER                    --   number while any required field is NULL —
  letting_agent TEXT                            --   it renders "estimate unavailable: N inputs
  agent_fee_pct REAL                            --   needed" instead (no guessed numbers, ever).
  has_mortgage INTEGER              -- 0/1; NULL = UNKNOWN (HANDOFF Q1)
  annual_mortgage_interest_minor INTEGER        -- from lender's annual certificate
  mortgage_rate_pct REAL            -- Phase 10 fallback: rate + balance below estimate the
  mortgage_balance_minor INTEGER    --   interest when the certificate figure is unknown (OUTSTANDING
                                     --   balance, not original loan); certificate always wins if set
  is_leasehold INTEGER              -- ground rent / service charge allowability (HANDOFF Q4)
  registered_for_sa INTEGER         -- NULL = UNKNOWN (HANDOFF Q2 — deadline-critical)
  utr TEXT                          -- if registered
  employment_gross_annual_minor INTEGER         -- to place rental profit in the right Scottish band
  updated_at TEXT NOT NULL
```

## 6. Tax ledger & documents

```sql
tax_years                           -- seeded from the tax year rental letting began (PRIVATE.md) onwards
  key TEXT PK                       -- '2026-27'
  start_date TEXT NOT NULL          -- '2026-04-06'
  end_date TEXT NOT NULL            -- '2027-04-05'

tax_documents
  id INTEGER PK
  tax_year TEXT NOT NULL REFERENCES tax_years(key)
  source TEXT NOT NULL              -- 'gmail' | 'manual'
  gmail_message_id TEXT UNIQUE      -- idempotency for the mail pipeline
  doc_type TEXT NOT NULL            -- 'rent_statement' | 'agent_invoice' | 'mortgage_interest_cert'
                                    -- | 'insurance' | 'repair_invoice' | 'ground_rent' | 'other'
  received_at TEXT NOT NULL
  from_addr TEXT
  subject TEXT
  file_path TEXT NOT NULL           -- under tax-documents/<tax_year>/ (gitignored)
  amount_minor INTEGER              -- parsed if confidently found; NULL otherwise (human fills in)
  amount_confidence TEXT NOT NULL DEFAULT 'none'  -- 'parsed' | 'guessed' | 'none'
  reviewed INTEGER NOT NULL DEFAULT 0             -- human has confirmed type + amount
  notes TEXT

rental_ledger                       -- the SA105-shaped ledger; one row per income/expense event
  id INTEGER PK
  tax_year TEXT NOT NULL REFERENCES tax_years(key)
  local_date TEXT NOT NULL
  kind TEXT NOT NULL                -- 'income' | 'expense'
  expense_type TEXT                 -- TAX.md §4 taxonomy: 'agent_fees' | 'insurance' | 'repairs'
                                    -- | 'ground_rent_service' | 'other_allowable'
                                    -- | 'mortgage_interest' (NOT deducted — S24 credit, TAX.md §5)
                                    -- | 'capital_improvement' (tracked, NOT allowable — CGT memo)
  amount_minor INTEGER NOT NULL     -- positive; kind carries the sign semantics
  source TEXT NOT NULL              -- 'transaction' | 'document' | 'manual'
  transaction_id INTEGER REFERENCES transactions(id)
  tax_document_id INTEGER REFERENCES tax_documents(id)
  notes TEXT
  INDEX (tax_year, kind)
```

`tax_year` for a date = the 6 Apr–5 Apr window containing it — one helper in
`app/dates.py` (`tax_year_of('2026-04-05') == '2025-26'`), unit-tested on the
boundaries. Year summaries (gross rents, allowable total, profit, S24 credit, the
allowance-vs-expenses comparison) are **computed, never stored** — `engines/tax.py`
over these rows + `tax_config`, per TAX.md §5.

## 7. Savings deals, tips, splits

```sql
deal_runs                           -- one per research run (API.md §4)
  id INTEGER PK
  run_at TEXT NOT NULL
  method TEXT NOT NULL              -- 'agent_research' | 'manual'
  sources_json TEXT NOT NULL        -- [{url, fetched_at}] — cite-with-date discipline
  file_path TEXT NOT NULL           -- data/deals/2026-07-13.json (raw findings kept)

savings_deals
  id INTEGER PK
  deal_run_id INTEGER NOT NULL REFERENCES deal_runs(id)
  provider TEXT NOT NULL            -- 'Chip', 'Coventry BS', ...
  product TEXT NOT NULL
  aer_pct REAL NOT NULL
  access TEXT NOT NULL              -- 'easy' | 'notice' | 'limited_withdrawals'
  min_deposit_minor INTEGER
  fscs INTEGER NOT NULL DEFAULT 1
  is_isa INTEGER NOT NULL DEFAULT 0
  source_url TEXT NOT NULL
  notes TEXT                        -- "rate includes 3-month bonus", etc.

tips                                -- rule-engine output, regenerated per period (API.md §6c)
  id INTEGER PK
  user_id INTEGER NOT NULL REFERENCES users(id)
  rule_key TEXT NOT NULL            -- 'category_trending_up' | 'cancel_candidate' | ...
  period TEXT NOT NULL              -- '2026-07'
  severity TEXT NOT NULL            -- 'info' | 'worth_a_look'  (deliberately no 'alarm')
  title TEXT NOT NULL
  body TEXT NOT NULL
  data_json TEXT                    -- the numbers behind the tip, for the UI to chart
  dismissed INTEGER NOT NULL DEFAULT 0
  UNIQUE (user_id, rule_key, period)

split_entries                       -- Warikan (only if PLAN §4 S3 accepted)
  id INTEGER PK
  user_id INTEGER NOT NULL REFERENCES users(id)
  local_date TEXT NOT NULL
  description TEXT NOT NULL
  total_minor INTEGER NOT NULL
  my_share_minor INTEGER NOT NULL   -- default total/2, editable
  paid_by TEXT NOT NULL             -- 'me' | 'partner'
  transaction_id INTEGER REFERENCES transactions(id)  -- one-tap from a Starling row
  settled INTEGER NOT NULL DEFAULT 0
  settled_at TEXT
```

## 7a. Gift-occasion budgets & personal wants (goals 10-11, Phase 9)

```sql
gift_occasions                      -- goal 10 (PLAN §3 row 10) — a sinking-fund-style
  id INTEGER PK                     --   budget per gift-giving occasion. label/limit/date are
  user_id INTEGER NOT NULL REFERENCES users(id)  -- 100% user-entered, never seeded (PRIVATE.md)
  label TEXT NOT NULL
  limit_minor INTEGER               -- NULL = no limit set yet — never a fabricated £0 cap
  target_date TEXT
  created_at TEXT NOT NULL

gift_items
  id INTEGER PK
  occasion_id INTEGER NOT NULL REFERENCES gift_occasions(id)
  label TEXT NOT NULL
  price_minor INTEGER NOT NULL
  bought INTEGER NOT NULL DEFAULT 0
  bought_date TEXT
  created_at TEXT NOT NULL

want_items                          -- goal 11 (PLAN §3 row 11, refined) — a personal-wants
  id INTEGER PK                     --   wishlist item. The affordability verdict
  user_id INTEGER NOT NULL REFERENCES users(id)  -- (engines/affordability.py) is always computed
  label TEXT NOT NULL               -- live from goals+safe-to-spend, never stored here
  price_minor INTEGER NOT NULL
  bought INTEGER NOT NULL DEFAULT 0
  created_at TEXT NOT NULL
```

### 7a-i. The affordability check (`engines/affordability.py`, pure)

`check_affordability(price_minor, headroom_minor, goal_projection_before, goal_projection_after)`
— composed from two already-computed figures, nothing new:

1. If `price_minor <= headroom_minor` (this period's safe-to-spend remaining, for a want; an
   occasion's own remaining budget excluding the item itself, for a gift item — same function,
   different headroom) → `fits_now`.
2. Otherwise run `engines/goals.project_goal` twice for the relevant active goal (`house_deposit`
   for a want; gift items never touch a savings goal) — once at the current balance, once with
   the price subtracted — and compare `status`/`catch_up_per_month_minor` before vs after. A
   status downgrade (`on_track`→`behind`) or a bigger catch-up while already behind →
   `not_yet`, with a weeks-delay estimate from the goal's own trend (ceiled, never flatters,
   ARCHITECTURE §6) when a trend exists. Otherwise → `fits_from_spare_cash`.
3. `unknown` when neither a headroom figure nor a goal exists yet (fresh setup state).

`engines/gifts.occasion_summary(limit_minor, item_prices_minor)` is the separate, simpler
aggregate for goal 10's own bubble content — `{spent_minor, limit_minor, remaining_minor,
verdict: 'no_limit_set'|'under_limit'|'over_limit'}` — over-limit is calm information, not a
guilt state (PLAN §6 rule 8).

## 8. Integrity rules

- All writes are per-authenticated-user; no endpoint accepts a `user_id`.
- Sync idempotency: `transactions (account_id, provider_uid)` and
  `balance_snapshots (account_id, local_date)` unique constraints mean any sync can be
  re-run safely; `tax_documents.gmail_message_id` does the same for mail.
- `manual` categorisations and `user_verdict`s survive every re-sync and re-detection
  run (§2, §3.5).
- `raw_json` and `detail_json` never appear in an API response — they exist for
  debugging and future re-parsing only.
- Deletions: transactions are never deleted (Starling may mark them declined/refunded —
  `settled`/amount update in place); `exclude_from_spending` is the user-facing "hide".
