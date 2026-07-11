# Kakeibo — UK Rental Income Tax (the estimator's spec)

## 0. Disclaimer — load-bearing, repeated in the UI

**Kakeibo estimates for planning purposes only.** It is not tax advice, it is not an
accountant, and it does not replace HMRC's own calculators or a professional when a
real Self Assessment return is filed. The estimator's job is to keep January from
being a surprise and to keep the paperwork organised — the filed numbers are checked
by a human (or their accountant) against HMRC, every year, no exceptions. This block
renders on every tax surface (DESIGN.md §4g) and every estimate response carries a
`disclaimer` string (API.md §5).

Second load-bearing rule: **the estimator never guesses.** Its inputs (§2) are config;
while any required input is missing it returns `estimate: null` +
`missing_inputs: [...]`, and the UI shows "estimate needs N inputs" — not a number
built on invented assumptions. A wrong-but-confident tax figure is the worst output
this app could produce.

## 1. The facts (and which tax years they touch)

The user lets out a house he owns while living elsewhere, since a specific date in 2025
(exact date: PRIVATE.md). Rental income is not PAYE-taxed → **Self Assessment**, UK
property pages (SA105). He is a **Scottish taxpayer** (resident in Scotland), which
matters: property profit is non-savings/non-dividend income and is therefore taxed at
**Scottish rates and bands**, stacked on top of his employment income (§3).

| Tax year | Rental months | Status |
|---|---|---|
| 2025-26 (6 Apr 2025 – 5 Apr 2026) | Partial — letting began mid-year (PRIVATE.md) | **First SA year. If not yet registered: register by 5 Oct 2026; file online + pay by 31 Jan 2027.** Paperwork lives in `tax-documents/2025-26/`. |
| 2026-27 (6 Apr 2026 – 5 Apr 2027) | 12 | Current year — the live estimate the dashboard shows. |

Whether he is *already* registered for SA (has a UTR) is **unknown** — HANDOFF Q2, and
the single most time-sensitive question in this project (today is 10 July 2026; the
registration deadline for 2025-26 is under three months away). The
`sa_registration_deadline` tip (API.md §6c) exists precisely for this.

## 2. Config inputs (`tax_config`, DATA_MODEL.md §5) — the open questions as schema

The maths below branches on facts we do not have. They are config fields, surfaced as
a setup form, mirrored as HANDOFF.md open questions Q1–Q5:

| Field | Why it changes the maths |
|---|---|
| `has_mortgage` on the rented house | If yes, interest is relieved only via the 20% Section 24 credit (§5b) — typically the largest single number in the computation. If no, the property allowance route becomes far more competitive (§5c). **Never assume either way.** |
| `annual_mortgage_interest_minor` | From the lender's annual mortgage interest certificate (the Gmail pipeline hunts for exactly this document). Interest only — capital repayments are never relievable. **Phase 10 fallback:** if this is unset but `mortgage_rate_pct` and `mortgage_balance_minor` (the *outstanding* balance, not the original loan) are both set, the engine derives `estimated_interest = round(mortgage_balance_minor × mortgage_rate_pct / 100)` and uses it — with a visible `assumptions` line saying it's an estimate, not the certificate figure (same "assumptions, never silent" pattern as the rates-year fallback below). The exact certificate figure always wins when both are present. |
| `is_leasehold` | Ground rent/service charges are allowable expenses only if actually payable (§4). This is about the user's own ownership structure of the house (does he hold it via a lease from a separate freeholder?) — **not** about the letting arrangement with the tenant, a common point of confusion (§2's field help spells this out explicitly, docs/phases/PHASE-10-post-launch-fixes.md item 7). |
| `registered_for_sa` / `utr` | Drives the deadline tips and the §6 checklist rendering. |
| `employment_gross_annual_minor` | Places rental profit in the correct Scottish band(s) — the marginal rate on rental profit is probably 21% or 42% depending on salary (§3), and guessing wrongly misstates the estimate by half. |
| `monthly_rent_minor`, `letting_agent`, `agent_fee_pct` | Gross rents + the recurring agent-fee expense; also configures the Gmail query (API.md §3c). |

## 3. How rental profit is taxed for a Scottish taxpayer

Order of computation the engine follows (`engines/tax.py`, pure functions over config
+ `rental_ledger` rows):

1. **Property business profit** (§5a) is computed for the tax year on the **cash
   basis** (default for property businesses with receipts ≤ £150,000 — ⚠️ verify the
   threshold is unchanged for the year being computed; accruals election is out of
   scope for v1).
2. Profit stacks **on top of employment income** as non-savings income. Personal
   allowance £12,570 (frozen; ⚠️ verify per year) is consumed by employment first.
3. Scottish rates/bands apply. **2025-26 table** (the engine stores rates as per-year
   config data, `engines/tax_rates.py` — adding a year = adding a dict, never editing
   logic; **2026-27 values must be entered from the Scottish Budget when Phase 5 is
   built — ⚠️ verify, do not copy forward silently**):

   | Band (total income incl. PA) | Rate |
   |---|---|
   | £12,571 – £15,397 | starter 19% |
   | £15,398 – £27,491 | basic 20% |
   | £27,492 – £43,662 | intermediate 21% |
   | £43,663 – £75,000 | higher 42% |
   | £75,001 – £125,140 | advanced 45% |
   | over £125,140 (PA tapers from £100k) | top 48% |

   Practical consequence: on a typical professional salary (the user's real
   employment context: PRIVATE.md) the rental profit most likely lands entirely in
   **higher (42%)**, or straddles intermediate/higher — which is why
   `employment_gross_annual_minor` is a required input.
4. **Section 24 finance-cost credit** (§5b) is then subtracted from the tax due — a
   *tax reduction*, not an expense deduction.
5. The engine computes the whole thing twice — actual-expenses route vs property
   allowance route (§5c) — and reports both plus which is better (API.md §5,
   `comparison`).

### National Insurance — the correct answer is (almost certainly) £0

The brief asked for "Class 2/4 NIC on rental profit". Stated plainly so nobody builds
the wrong thing: **ordinary residential letting is not a trade, so its profits are not
liable to Class 4 NIC, and Class 2 does not apply** (HMRC treats property income as
investment income unless the activity amounts to a business of trading — running a
guest house, providing substantial services, etc., none of which apply to a single
let). Additionally, Class 2 NIC was effectively abolished for the self-employed from
April 2024. The engine therefore returns `nic_due: 0` with an explanatory note, and
this doc is the citation trail (⚠️ verify against current HMRC NIM guidance at
implementation — if HMRC's position on property businesses and voluntary Class 2 has
moved, update here first). His employment NI is handled by PAYE and is out of scope.

## 4. Allowable expenses (the `expense_type` taxonomy, DATA_MODEL.md §6)

Cash-basis, wholly-and-exclusively for the letting:

| `expense_type` | Allowable? | Notes |
|---|---|---|
| `agent_fees` | ✅ | letting agent's % + tenancy setup/renewal fees |
| `insurance` | ✅ | landlord buildings/contents/rent-guarantee |
| `repairs` | ✅ | like-for-like repair & maintenance (boiler fix, repaint, broken fence). **Not improvements** — see `capital_improvement` |
| `ground_rent_service` | ✅ if leasehold (config-gated) | ground rent, factor/service charges |
| `other_allowable` | ✅ | accountancy for the rental, advertising for tenants, landlord registration (mandatory in Scotland), gas/electrical safety certificates, EPC, council tax/utilities **only** for void periods the landlord actually paid, replacement of domestic items relief (like-for-like replacement of furniture/appliances — the *initial* purchase is not allowable), mileage to the property at HMRC flat rates |
| `mortgage_interest` | ❌ as deduction / ✅ as 20% credit | recorded in the ledger but **excluded from expense totals**; feeds §5b only. Capital repayments: nothing, ever |
| `capital_improvement` | ❌ | extensions, upgrades beyond like-for-like. Tracked anyway — they enter the CGT base cost when the house is eventually sold; Kakeibo keeps the receipts folder warm (v1 does **no** CGT computation) |

Pre-letting expenses (getting the house tenant-ready before the letting start date,
PRIVATE.md) are allowable as if incurred on day one if within 7 years and
otherwise-allowable — relevant to the 2025-26 return; the ledger accepts pre-tenancy
dates for that year. Losses: a property
business loss carries forward automatically against future property profits (the
engine persists nothing — it recomputes from ledger rows, so a loss year simply feeds
the next year's computation via `loss_brought_forward`, itself derived).

## 5. The computation, precisely

### 5a. Route 1 — actual expenses + Section 24 credit

```
gross_rents      = Σ ledger income rows in year
allowable        = Σ ledger expense rows, types marked ✅ in §4 (mortgage_interest EXCLUDED)
profit           = max(0, gross_rents − allowable − loss_brought_forward)
tax_on_profit    = scottish_tax(employment_income + profit) − scottish_tax(employment_income)
                   # the marginal-stacking definition; handles band-straddling exactly
s24_credit       = 20% × min(finance_costs,            # ledger mortgage_interest rows
                             profit,                   # property profits cap
                             adjusted_income_above_pa) # rarely binding here, computed anyway
                   # 20% is the UK basic rate by statute, even for Scottish taxpayers
                   #   (⚠️ verify — ITTOIA s274A; unused finance costs carry forward)
tax_due_route1   = tax_on_profit − s24_credit          # floor 0; excess credit carries forward
```

`finance_costs` above resolves in this order (`routers/tax.py`'s `_resolve_mortgage_interest`,
Phase 10): the exact `annual_mortgage_interest_minor` certificate figure if set; else
`round(mortgage_balance_minor × mortgage_rate_pct / 100)` if both are set (outstanding
balance, not the original loan — interest is charged on what's left to repay); else the
ledger's own `mortgage_interest` rows. The rate×balance path adds an `assumptions` line
to the estimate response so it's never mistaken for the certificate's precise figure.

### 5b. Section 24, spelled out (because it is routinely misunderstood)

Since 2020-21, **no** residential mortgage interest is deductible from rental income.
Instead the taxpayer gets a **basic-rate (20%) tax reducer** on the lowest of finance
costs / property profits / adjusted total income above the personal allowance. For a
42%-band Scottish landlord this means: £3,600 of interest does **not** reduce profit —
it yields a £720 credit, while the £3,600 itself was effectively taxed at 42%
(£1,512). This asymmetry is exactly why "is there a mortgage, and how much interest"
(HANDOFF Q1) dominates the estimate, and why the app must not guess it.

### 5c. Route 2 — the £1,000 property income allowance

```
if gross_rents ≤ £1,000: no tax, no reporting requirement for this income (full relief)
else (partial relief):    profit = gross_rents − £1,000; NO actual expenses deductible;
                          engine assumes NO s24 credit combinable with the allowance
                          (⚠️ verify against SA105 notes / PIM at implementation — the
                          conservative assumption can only overstate route 2's tax,
                          never understate the eventual bill)
tax_due_route2 = scottish_tax(employment + profit) − scottish_tax(employment)
```

The estimate response always carries both routes and `method_used` = the cheaper
(API.md §5). Rule of thumb the UI may echo: with an agent + insurance + any mortgage,
route 1 nearly always wins; the allowance exists for low-expense edge cases.

### 5d. Worked example — pinned as the unit test (illustrative config, NOT real facts)

Illustrative config only — none of these are the user's real figures, which are unknown
pending HANDOFF Q1/Q3/Q5: rent £850/mo (full year 2026-27 → gross £10,200); agent 10%
(£1,020); insurance £240; one repair £600; mortgage interest £3,600 (**placeholder
pending HANDOFF Q1**); employment £48,000 gross (**placeholder pending HANDOFF Q5**);
Scottish 2025-26 rates (per §3 note); no loss b/f.

```
Route 1: allowable = 1,020+240+600 = £1,860 → profit £8,340
         £48,000 already > £43,662 → all profit in higher band: 8,340 × 42% = £3,502.80
         s24 = 20% × min(3,600, 8,340, big) = £720
         tax due = £2,782.80
Route 2: profit = 10,200 − 1,000 = £9,200 → 9,200 × 42% = £3,864.00; no credit
Engine: method_used = expenses_plus_s24, tax_due_minor = 278280, s24_credit_minor = 72000
```

A second pinned case must cover band-straddling (employment £41,000 → profit taxed
partly at 21%, partly 42%) and a third the allowance winning (expenses £300, no
mortgage). Hand-compute all three in the test file with comments — the tests are the
audit trail.

## 6. Self Assessment mechanics & deadlines (the checklist the TaxPage renders)

| When | What |
|---|---|
| **5 Oct 2026** | Deadline to register for SA for 2025-26 (first rental year) if not already registered → SA1/online, HMRC issues UTR. **The app's loudest allowed nudge until Q2 is answered.** |
| 31 Oct 2026 | 2025-26 paper filing deadline (irrelevant — file online) |
| 30 Dec 2026 | 2025-26 online deadline **if** requesting collection via PAYE code (bill < £3,000) — worth surfacing as an option |
| **31 Jan 2027** | 2025-26 online filing + payment deadline; possibly first payment on account for 2026-27 |
| 31 Jul 2027 | Second 2026-27 payment on account, if POAs apply |
| 31 Jan 2028 | 2026-27 filing + balancing payment |

**Payments on account:** required when the SA bill exceeds £1,000 **unless** ≥80% of
the year's total tax was collected at source (PAYE). With a decent PAYE salary and a
~£2–3k rental bill this test is genuinely borderline — the engine computes it properly
(it knows both numbers) rather than assuming, and the estimate response includes
`payments_on_account: {required, amounts, dates} | null`.

**Making Tax Digital for Income Tax:** mandatory from Apr 2026 only where qualifying
gross income (property + sole-trade combined) exceeds £50,000; £30,000 from Apr 2027;
£20,000 announced for Apr 2028 (⚠️ verify current thresholds at implementation). The
user's real gross rental income is unknown pending HANDOFF Q3, but is expected to sit
well under the threshold for now; the TaxPage shows a quiet one-liner with the actual
computed headroom, because quarterly digital filing would change this feature
materially if that ever changes.

**What the accountant handover contains** (the deliverable of goal 8a):
`tax-documents/<year>/` — every pulled statement/certificate/invoice, dated and
typed — plus a ledger CSV export (`GET /api/tax/ledger?year=…&format=csv`, one line
item per row with source document references) and the estimate's computation printout.
An accountant should be able to file from that folder without asking for anything
except the questions Kakeibo already lists as missing.

## 7. Acceptance criteria (Phase 5 verifies)

- [ ] All three §5d worked examples pass as unit tests, hand-computed values in
      comments; band-straddling case exact to the penny.
- [ ] Estimator returns `estimate: null` + correct `missing_inputs` while any of
      `has_mortgage` / `annual_mortgage_interest` (if mortgage) /
      `employment_gross_annual` is unset — verified by API test, and the UI renders
      the setup card, not zeros.
- [ ] Rates live in per-year config data; computing 2026-27 with 2025-26 rates emits
      a visible `assumptions: ["2026-27 Scottish rates not yet entered — using
      2025-26"]` in the response (never silent).
- [ ] `mortgage_interest` ledger rows are excluded from `allowable_expenses` totals
      and included in the S24 credit; `capital_improvement` rows appear in neither.
- [ ] `tax_year_of()` boundary tests: 5 Apr vs 6 Apr land in different years.
- [ ] `nic_due` is 0 with the §3 explanatory note in the response.
- [ ] Disclaimer text present in every estimate response and on every tax UI surface.
- [ ] Deadline checklist renders from `tax_config` state (registered vs not) with the
      §6 dates; the 5 Oct 2026 nudge fires while `registered_for_sa` ∈ {NULL, 0}.
