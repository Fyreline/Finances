# Savings-deals research prompt — docs/API.md §4, docs/DEPLOYMENT.md §4d

This is **not a script** — there is no dependable free UK savings-rate API
(API.md §4's constraint), so this feature runs on periodic *agent-assisted
research*, not a poll. This file is the reusable prompt/checklist a Claude
scheduled task (or a household member, manually) works through once a month
to write one new `data/deals/<YYYY-MM-DD>.json` file. The dashboard's Deals
bubble/DealsPage renders whatever the newest such file says, with its as-of
date always visible (DESIGN.md §4h) — it never claims to be live.

## What to search

- MoneySavingExpert's easy-access savings best-buy table
  (`moneysavingexpert.com/savings/savings-accounts-best-interest/`).
- 2–3 challenger/high-street banks' own "easy access savings" product pages
  directly (rates on aggregators can lag the provider's own page by a few
  days) — pick whichever currently sit at the top of the MSE table.
- Cross-check FSCS protection status on the provider's own page if not stated
  clearly on the aggregator (should be true for any UK-regulated bank/building
  society; flag `"fscs": false` only if genuinely uncovered, e.g. some
  fintech/e-money "savings" products aren't deposit accounts at all).

## What to record, per deal

| Field | Notes |
|---|---|
| `provider` | The bank/building society name, spelled as they brand it. |
| `product` | The product name (helps distinguish a provider's own multiple tiers). |
| `aer_pct` | Annual Equivalent Rate, as a plain number (`4.6`, not `"4.6%"`). |
| `access` | `"easy"` \| `"notice"` \| `"limited_withdrawals"` — v1 excludes fixed bonds and regular savers entirely (see "What to exclude" below), so this should almost always be `"easy"`. |
| `min_deposit_minor` | Integer pence. `0` if there's no minimum. |
| `fscs` | `true`/`false` — UK Financial Services Compensation Scheme coverage. |
| `is_isa` | `true`/`false` — a Cash ISA variant of the same rate counts as a separate deal entry if you want to include it. |
| `source_url` | The exact page you read the rate from — this becomes the clickable citation on every deal card. Never the aggregator's homepage; the specific rates page. |
| `notes` | Anything that qualifies the headline rate: an introductory bonus and when it drops off, withdrawal limits per year, whether the rate is variable. |

Record 4–8 deals per run — enough for a meaningful comparison, not an
exhaustive market scrape.

## What to exclude (v1)

- **Fixed-rate bonds** — different liquidity trade-off than "easy access",
  would need its own comparison axis (term length) to be a fair listing.
- **Regular savers** — capped monthly deposit structure doesn't compare
  cleanly against a lump-sum easy-access balance.
- Both are candidates for a v2 `access` value or a second research pass, not
  in scope for this feature's first cut (docs/phases/PHASE-6-deals-splits.md
  item 1).

## The file to write

`data/deals/<YYYY-MM-DD>.json` (today's date, the date you did the research —
this becomes `run_at` and the page's "checked <date>" line):

```json
{
  "run_at": "2026-08-13T09:00:00Z",
  "method": "agent_research",
  "sources": [
    {"url": "https://www.moneysavingexpert.com/savings/savings-accounts-best-interest/", "fetched_at": "2026-08-13T09:00:00Z"},
    {"url": "https://www.example-bank.co.uk/savings/easy-access", "fetched_at": "2026-08-13T09:05:00Z"}
  ],
  "deals": [
    {
      "provider": "Example Bank",
      "product": "Easy Access Saver",
      "aer_pct": 4.6,
      "access": "easy",
      "min_deposit_minor": 0,
      "fscs": true,
      "is_isa": false,
      "source_url": "https://www.example-bank.co.uk/savings/easy-access",
      "notes": "includes a 12-month 0.8% bonus, reverts to the base rate after"
    }
  ]
}
```

Every field above the `deals` array's per-deal `provider`/`product`/`aer_pct`/
`access`/`source_url` is required — the import endpoint (`POST
/api/deals/import`, also run automatically at server startup) rejects the
whole file if any deal is missing a `source_url`, matching the "no deal
without a working source link and a date can exist" rule
(docs/phases/PHASE-6-deals-splits.md acceptance list).

## After writing the file

Nothing else to do by hand — the server imports the newest file in
`data/deals/` automatically on its next startup, and `POST
/api/deals/import` re-scans on demand (e.g. right after this research run,
via `curl -X POST http://127.0.0.1:8200/api/deals/import -H "Authorization:
Bearer <token>"` if you want it to show up before the next restart). A run
older than 35 days automatically starts showing the staleness banner on the
DealsPage — that's the safety net if a monthly run is ever missed, not
something this checklist needs to track separately.

## Setting up the recurring pass

See docs/DEPLOYMENT.md §4d for how to wire this prompt into a monthly
scheduled Claude task (the `schedule` skill / `mcp__scheduled-tasks__*`
tools), or the manual alternative if the household prefers a human-triggered
monthly ritual instead.
