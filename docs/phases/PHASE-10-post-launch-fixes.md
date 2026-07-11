# Phase 10 — post-launch fixes (real user feedback, 2026-07-11)

Owner: Sonnet. The app is live with real data for the first time; these are seven items
the user reported from actual use. Root causes for every bug here were already
diagnosed by the orchestrator via code inspection (not guessed) — read each item's
"Root cause" line as established fact, not a hypothesis to re-derive.

## 1. Detail-panel connector should match Mishka Hub's current liquid-glass style

Kakeibo's `components/BraceConnector.tsx` is a simplified stand-in — its own doc
comment admits it's "a simplified port of Mishka Hub's liquid-connector concept... a
single stroked brace rather than a filled liquid-glass shape." The user wants it to
actually look like Mishka Hub's current treatment, not this placeholder.

Mishka Hub's real pattern (`MishkaHub/apps/web/src/components/MovieCard.tsx`, search
`expanded`): on expand, a gradient halo — `absolute -inset-x-1.5 -top-2 -bottom-2
rounded-t-xl rounded-b-2xl bg-gradient-to-t from-liquid from-25% to-transparent to-70%`
— plus `border-liquid` on the card border instead of the default `border-line`. The
`--color-liquid` token (`#c5e0dd` light / `#223c4e` dark, comment: "Mishka's connector
surface / Michi's trail") is **already in the shared canonical `theme.css`** that
Kakeibo mirrors — it's sitting there unused, no sync-script change needed, just start
using `border-liquid`/`from-liquid`/`bg-liquid` (check `theme.css` for the exact
Tailwind class names it generates for this token; likely `border-liquid`,
`from-liquid` work directly via Tailwind's arbitrary-token resolution the same way
`border-clay`/`text-clay` already do elsewhere in this codebase).

Adapt (don't literally copy) for Kakeibo's bubble shape: replace or augment
`BraceConnector`'s stroke color/opacity with `var(--color-liquid)`, and give the
active bubble + its detail panel container a `border-liquid`-tinted border and/or a
subtle `from-liquid` gradient edge on expand, consistent with DESIGN.md §3c's existing
brace-connector spec (peak tracks the active bubble). Update DESIGN.md §3c if the
connector's visual treatment changes materially. Keep it "a desk, not a poster wall" —
subtler than Mishka Hub's movie-card treatment, not a copy-paste.

## 2. Bubble glances look stale/empty even when detail panels have real data

**Root cause (confirmed):** `App.tsx`'s `AuthenticatedApp` fetches
`GET /api/summary/bubbles` exactly once, in a `useEffect` with an empty dependency
array, on mount. It never refetches. Detail panels (`useGoals`, `useSafeToSpend`,
`useNetWorth`, etc.) each fetch their own fresh data independently every time they're
opened. If real data changes after the initial page load (a sync completing in the
background, config being saved, anything), the one-shot `summary` used for every
bubble's collapsed glance goes stale while detail panels — which fetch fresh on open —
correctly show current data. This is exactly what happened: the user's first sync
completed seconds after their first page load, so `summary` was fetched before real
data existed.

**Fix:** refetch `summary` in `AuthenticatedApp` on these triggers, not just mount:
- When a detail panel closes (`activeKey` transitions from non-null to null) — the
  user may have changed config, dismissed something, or time has simply passed.
- On window focus (`window.addEventListener('focus', ...)`) — standard
  stale-while-revalidate pattern, catches "left the tab open, sync happened".

Keep the existing single-fetch-per-refresh principle (Phase 7's "one fetch renders the
whole collapsed home") — this is refetching the SAME one call on a couple of sensible
triggers, not adding polling or a second endpoint. Debounce/guard against a refetch
firing while one is already in flight (simple `useRef` in-flight flag is enough, no
new library).

## 3. Safe-to-spend detail panel: "Loading…" forever on error

**Root cause (confirmed):** `hooks/useSafeToSpend.ts` correctly has `.catch()` and
sets an `error` string on failure — but `components/details/SafeToSpendDetail.tsx`'s
render logic is `if (loading || !data) return <p>Loading…</p>` and **never reads
`error` at all**. Any fetch failure (network hiccup, transient 401, a genuine backend
error) leaves `loading=false, data=null, error="<message>"`, and the component still
matches the `!data` branch — showing "Loading…" indefinitely with the actual error
silently discarded.

**Fix:** add a proper error branch before the loading check:
```
if (error) return <p className="text-[13px] text-ink-mid">{error} <button onClick={reload} className="underline">retry</button></p>
```
(style to match this file's existing patterns, e.g. `ConfigForm`'s error paragraph
style two components up in the same file). Apply the same fix pattern to **every other
detail component that uses a similar loading-hook pattern** (`useGoals.ts`'s consumers,
`NetWorthDetail`, `RecurringDetail`, `WantsGiftsDetail`, `DealsDetail`, `TaxDetail`) —
grep each for a hook that exposes `error` and confirm the component's render logic
actually branches on it before assuming `!data` means "still loading". Several of these
were written before Phase 9's real-credential testing surfaced this exact class of bug
in `SafeToSpendDetail`; audit all of them now that it's found, don't just patch the one
reported instance.

## 4. Recurring payments: dismiss items that aren't real subscriptions

**Root cause / existing mechanism (confirmed):** the backend already fully supports
dismissing a recurring row so it never resurfaces — `PATCH /api/recurring/{id}` with
`user_verdict="cancelled"` sets `status="dismissed"`, and `rebuild_recurring()` in
`insights_service.py` explicitly never resurrects a `dismissed` row on re-detection
(comment: "Never resurrect a dismissed row"). The mechanism is right; the **label is
wrong**. "Cancelled" implies "this was a real subscription and I cancelled it" — wrong
framing for a mortgage standing order or a Starling Space transfer to savings, which
were never subscriptions to begin with and are still very much active.

**Fix:**
- `app/routers/recurring.py`: add a new verdict value to `_VERDICTS` — e.g.
  `"not_recurring"` (pick a name that reads honestly; check `docs/API.md` §5's
  Recurring section for whether a name is already implied, otherwise choose one and
  document it there). Handling mirrors `"cancelled"` exactly: set
  `row.user_verdict = "not_recurring"` and `row.status = "dismissed"`.
- `apps/web/src/api.ts`: add `'not_recurring'` to the `RecurringVerdict` union.
- `components/details/RecurringDetail.tsx`: add a third action button alongside
  keep/cancelled — label it something like "not a subscription" or "remove" (calm,
  factual, matches this file's existing button styling) — that PATCHes with the new
  verdict. Keep the existing "cancelled" button for genuine subscription cancellations
  (Netflix, gym, etc.) — don't merge the two, they mean different things to the user
  even though they resolve to the same backend `status="dismissed"` state.
- Update `docs/DATA_MODEL.md` §3a and `docs/API.md` §5 to document the new verdict
  value and when to use which of the three.
- Server test: PATCH with the new verdict sets `status="dismissed"` and the row is
  excluded from a subsequent `rebuild_recurring()` call, mirroring the existing
  "cancelled" test's assertions.

Do NOT auto-exclude `savings_transfer`-category transactions from recurring detection
entirely — the user might still want to see "recurring transfer to savings" as
informational. The fix is giving them an easy one-click way to say "not a subscription"
per-item, not silently hiding a category.

## 5. Spending breakdown: clicking a category should filter Transactions tab

**Root cause / existing scaffolding (confirmed):** `TransactionTable.tsx` already
accepts an `initialFilters?: { category?: string; ... }` prop with a doc comment
literally anticipating this: "Pre-set filters (e.g. a category clicked in the
Breakdown tab, Phase 4)" — it was never wired up. `CategoryBreakdown.tsx`'s category
rows currently have zero click handling.

**Fix:**
- `components/CategoryBreakdown.tsx`: accept an `onSelectCategory?: (key: string) =>
  void` prop; add `onClick`/keyboard handling (role="button" or a real `<button>`
  wrapping each row) that calls it with the category's key. Visual affordance: hover
  state matching this file's existing interactive patterns (check `categoryChipClass`
  usage elsewhere for the house hover convention — likely `hover:bg-paper-deep` or
  similar per DESIGN.md).
- `components/details/SpendingDetail.tsx`: thread a category selection through —
  clicking a category in `BreakdownTab` should call `setTab('transactions')` AND pass
  the selected category key down so `<TransactionTable />` receives
  `initialFilters={{ category: selectedKey }}` on the next render. Use the existing
  `useTabHash` hash-routing (`#spending/transactions`) — consider whether the category
  filter should also live in the hash (e.g. `#spending/transactions?category=fun`) for
  deep-link/back-button consistency with how the rest of this app treats state, or a
  plain `useState` if that's simpler and consistent with how `TransactionTable`'s
  *own* internal filters (month/category/q) already work (check whether those are
  hash-synced or plain state — match that convention, don't invent a new one).
- Clear the selected category when switching to the Breakdown or Tips tab, so
  returning to Transactions later doesn't carry a stale filter from a different visit.

## 6. Tax config: mortgage interest should accept a rate, not just an absolute figure

**Current state:** `tax_config.annual_mortgage_interest_minor` only accepts an exact
annual £ figure ("From the lender's annual mortgage-interest certificate"). The user
knows their mortgage's fixed interest **rate** but not the exact annual interest
figure (which changes as a repayment mortgage amortizes — the interest portion
decreases each year even at a fixed rate, since it's calculated against a shrinking
balance).

**Fix — respect TAX.md §0's "never guess" rule; this must be an honest estimate, not
a silent invention:**
- Add two new nullable `tax_config` fields: `mortgage_rate_pct: float | None` and
  `mortgage_balance_minor: int | None` (outstanding balance — NOT original loan
  amount, since interest accrues on the current balance; if only the original loan
  amount is known, that's a documented, visibly-flagged approximation, not silently
  treated as current balance).
- When `annual_mortgage_interest_minor` is unset but both `mortgage_rate_pct` and
  `mortgage_balance_minor` are set, the tax estimator computes
  `estimated_interest = round(mortgage_balance_minor * mortgage_rate_pct / 100)` and
  uses it **with a visible flag** — add this to `TaxEstimate.assumptions` (the existing
  array used for the 2026-27-rates-unconfirmed case, `engines/tax.py` — same pattern,
  don't invent a new mechanism): something like `"Mortgage interest estimated from
  rate × balance, not your lender's exact certificate — swap in the real figure once
  you have it for an exact number."` This keeps `missing_inputs` correctly empty (an
  estimate now exists) while being transparent that it's an estimate, not the precise
  certificate figure — exactly the "assumptions, never silent" pattern this doc already
  uses for the rates gap.
- `routers/tax.py`'s `TAX_FIELD_HELP` dict: update `annual_mortgage_interest_minor`'s
  help text to mention the rate+balance alternative; add help text for the two new
  fields explaining balance = *outstanding*, not original loan amount.
- Web `TaxDetail.tsx`'s config form: add the two new fields, ideally with a small
  toggle or just both input pairs visible ("exact interest OR rate + balance") — keep
  it simple, this doesn't need to be clever UI, just functional and clearly labelled.
- `docs/TAX.md` §2/§5: document the estimation formula and its "assumptions" line.
- Server test: config with rate+balance only produces a non-null estimate with the
  assumptions line present; config with the exact figure set takes precedence over
  rate+balance if both happen to be set (exact known figure always wins).

## 7. Tax config: "leasehold" question is genuinely ambiguous wording

**Not a bug in the tax logic** — `is_leasehold` correctly gates whether ground-rent/
service-charge expenses are allowable (TAX.md §4), and that logic is untouched by this
fix. The problem is purely the field's help text: `routers/tax.py`'s
`TAX_FIELD_HELP["is_leasehold"]` currently reads "Ground rent / service charges are
allowable only if the property is leasehold" — technically correct but leaves a real
user unsure whether it's asking about *their own ownership structure* of the rented-out
house, or about *the letting arrangement with their tenant* (a live case: the user owns
the house outright/mortgaged and lets it to a tenant via an agency — that's completely
unrelated to whether the house itself is held leasehold).

**Fix — rewrite the help text to disambiguate explicitly:**
```
"Leasehold" is about how YOU own this house (do you hold it via a lease from a separate
freeholder, paying them ground rent/service charges — common for flats, rare for
houses) — it has nothing to do with renting the property out to a tenant, which is a
separate question. Most Scottish residential property has no leasehold structure at
all (feudal tenure was abolished in 2004) — if this doesn't sound familiar, the answer
is almost certainly "no".
```
(Trim/adapt for actual UI space constraints — this is the substance to convey, not
necessarily verbatim.) Apply the same "is this asking about MY ownership or the LETTING
arrangement" clarity check to any other tax_config field whose wording could plausibly
be misread the same way (skim `TAX_FIELD_HELP` fully) — `is_leasehold` isn't
necessarily the only ambiguous one.

## Hard constraints — same as every prior phase

- Money integer pence everywhere, no floats in a money path except the display-layer
  rate×balance estimate calc above (a legitimate float `mortgage_rate_pct`, rounded to
  pence at the point it becomes `estimated_interest`).
- No red-alert guilt UI — "not a subscription" dismissal, error states, everything
  stays calm/informational tone.
- No real personal figures ever committed — as always, any new test fixtures use
  clearly synthetic data.
- Read-only against every bank/API — none of this touches `app/integrations/`.
- Run pytest + typecheck + vitest + build before committing; full redaction sweep;
  update docs/HANDOFF.md's state table; commit prefix `phase-10:`.
- **After this deploys, the orchestrator (not this phase) is responsible for
  restarting the `com.kakeibo.api` LaunchAgent** — this phase touches backend files
  (routers/tax.py, routers/recurring.py, engines/tax.py, models.py) and per the
  2026-07-11 incident (docs/HANDOFF.md), a push alone does NOT restart the running
  backend process. Note this prominently in your final report so it isn't missed again.
