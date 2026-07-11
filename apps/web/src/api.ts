// Fetch wrapper w/ bearer token + 401 retry — port of Michi's api.ts
// (docs/ARCHITECTURE.md §3). Phase 1 only wired the auth + health surface;
// Phase 2 adds transactions/categories/rules/sync (docs/API.md §5) without
// touching this request plumbing. accounts/summary/goals/tax/deals land in
// later phases the same way.
import { forceLogout, getValidAccessToken } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8201'

export type IntegrationStatus = 'ok' | 'not_configured' | 'error' | 'stale'

export interface Health {
  status: string
  identity: 'reachable' | 'unreachable'
  integrations: {
    starling: IntegrationStatus
    trading212: IntegrationStatus
    gmail: IntegrationStatus
  }
  last_sync: {
    starling: string | null
    trading212: string | null
    gmail: string | null
  }
}

/** Shape of `users.settings_json` (docs/DATA_MODEL.md §1), all optional —
 * PUT /api/auth/settings is a merge-patch. */
export interface UserSettings {
  dashboard_tiles_order?: string[]
  hidden_suggestions?: string[]
}

export interface Me {
  id: number
  email: string
  display_name: string
  settings: UserSettings
}

class ApiError extends Error {
  code?: string
  status?: number
  constructor(message: string, opts?: { code?: string; status?: number }) {
    super(message)
    this.name = 'ApiError'
    this.code = opts?.code
    this.status = opts?.status
  }
}

async function parseErrorBody(res: Response): Promise<{ detail: string; code?: string }> {
  let detail = `${res.status} ${res.statusText}`
  let code: string | undefined
  try {
    const body = await res.json()
    if (body?.detail) detail = body.detail
    if (body?.code) code = body.code
  } catch {
    /* non-JSON error body (e.g. connection-refused proxies, plain 404 pages) */
  }
  return { detail, code }
}

async function doFetch(path: string, init: RequestInit, accessToken: string | null): Promise<Response> {
  const headers = new Headers(init.headers)
  if (accessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }
  return fetch(`${BASE}${path}`, { ...init, headers })
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    const token = await getValidAccessToken()
    res = await doFetch(path, init ?? {}, token)
    // A still-401 despite a "valid" token means the session died server-side
    // (e.g. the refresh token was revoked by the reuse-detection tripwire) —
    // try one silent refresh-and-retry before giving up.
    if (res.status === 401 && token) {
      const refreshed = await getValidAccessToken()
      if (refreshed && refreshed !== token) {
        res = await doFetch(path, init ?? {}, refreshed)
      }
    }
    if (res.status === 401) {
      forceLogout()
    }
  } catch (err) {
    // Network error / connection refused — the backend isn't up yet.
    throw new ApiError(err instanceof Error ? err.message : 'Network error', { code: 'network_error' })
  }
  if (!res.ok) {
    const { detail, code } = await parseErrorBody(res)
    throw new ApiError(detail, { code, status: res.status })
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** Exported for feature modules that own their response types — keeps this
 * file to plumbing + the small auth surface. */
export function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

/** JSON POST/PUT/PATCH twin of get<T>() — feature modules own the body/response types. */
export function post<T>(path: string, body: unknown, method: 'POST' | 'PUT' | 'PATCH' = 'POST'): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** DELETE twin of get<T>() — no body. */
export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

function buildQuery(path: string, params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${path}?${qs}` : path
}

// ------------------------------------------------------------------------
// Transactions, categories, rules, sync — docs/API.md §5 "Transactions"/
// "Sync". Types mirror the JSON shapes exactly (snake_case, integer pence);
// `money.ts` is still the only place that formats them for display.
// ------------------------------------------------------------------------
export interface CategoryBrief {
  id: number
  key: string
  label: string
}

export interface Category extends CategoryBrief {
  kind: 'income' | 'fixed' | 'discretionary' | 'rental' | 'transfer'
  viz_slot: number | null
  sort: number
}

export type CategorySource = 'provider' | 'rule' | 'manual'

export interface TransactionItem {
  id: number
  local_date: string
  counterparty: string | null
  reference: string | null
  amount_minor: number
  category: CategoryBrief | null
  category_source: CategorySource
  is_rental: boolean
  exclude_from_spending: boolean
  settled: boolean
}

export interface TransactionsPage {
  items: TransactionItem[]
  total: number
  page_size: number
}

export interface TransactionFilters {
  month?: string
  category?: string
  account?: number
  q?: string
  page?: number
}

export interface TransactionPatch {
  category_id?: number | null
  is_rental?: boolean
  exclude_from_spending?: boolean
}

export interface CategoryRule {
  id: number
  priority: number
  match_field: 'counterparty' | 'reference' | 'provider_category'
  pattern: string
  category_id: number
  set_is_rental: boolean
  set_exclude: boolean
}

export type SyncStatusValue = 'ok' | 'error' | 'not_configured'

export interface SyncRunStatus {
  provider: string
  started_at: string
  finished_at: string | null
  status: SyncStatusValue
  new_rows: number
  detail: string | null
}

// ------------------------------------------------------------------------
// Accounts, net worth, goals — docs/API.md §5 "Accounts & balances"/"Goals",
// docs/phases/PHASE-3-t212-goals.md. Types mirror the JSON shapes exactly.
// ------------------------------------------------------------------------
export type AccountStatus = 'ok' | 'not_configured' | 'stale'

export interface AccountItem {
  id: number
  provider: 'starling' | 'trading212' | 'manual'
  name: string
  kind: string
  latest_balance_minor: number | null
  latest_snapshot_date: string | null
  include_in_networth: boolean
  status: AccountStatus
}

export interface ManualAccountBody {
  name: string
  kind: string
  balance_minor: number
}

export interface ManualBalanceBody {
  balance_minor: number
  local_date: string
}

export interface NetWorthPoint {
  date: string
  total_minor: number
}

export interface NetWorthAccountBalance {
  account_id: number
  name: string
  balance_minor: number
}

export type EmergencyFundVerdict = 'unknown' | 'building_from_scratch' | 'below_guide' | 'within_range' | 'well_covered'

export interface EmergencyFund {
  months_of_cover: number | null
  verdict: EmergencyFundVerdict
  copy: string
}

export interface ContractorGap {
  pension_contributing: boolean | null
  fte_conversion_target_date: string | null
  fte_runway_goal: Goal | null
}

/** docs/PLAN.md §4 S1/S2/S4, docs/phases/PHASE-9-personal-goals.md §1-3 —
 * the Net Worth bubble hosts all three: the total + windowed sparkline is
 * the glance, the account breakdown/emergency-fund/contractor-gap sections
 * live in its detail view (docs/DESIGN.md §3b row 8). */
export interface NetWorth {
  total_minor: number
  by_account: NetWorthAccountBalance[]
  series: NetWorthPoint[]
  as_of: string | null
  emergency_fund: EmergencyFund
  contractor_gap: ContractorGap
}

export type GoalStatus = 'on_track' | 'behind' | 'no_trend'

export interface GoalSeriesPoint {
  date: string
  value_minor: number
}

export interface Goal {
  key: string
  label: string
  target_minor: number | null
  target_date: string | null
  current_minor: number
  baseline_minor: number
  baseline_date: string
  monthly_pledge_minor: number | null
  required_per_month_minor: number | null
  trend_per_month_minor: number | null
  projected_at_target_minor: number | null
  status: GoalStatus
  catch_up_per_month_minor: number | null
  series: GoalSeriesPoint[]
}

export interface GoalPatch {
  monthly_pledge_minor?: number | null
  target_minor?: number | null
  source_account_ids?: number[]
}

// ------------------------------------------------------------------------
// Summary & insights — docs/API.md §6a/§6b/§6c, Phase 4. Integer pence
// throughout; `money.ts` is the only formatter.
// ------------------------------------------------------------------------
export interface CommittedItem {
  label: string
  monthly_equivalent_minor: number
}

export interface GoalSetAsideItem {
  key: string
  amount_minor: number
}

export interface SafeToSpend {
  safe_to_spend_minor: number | null
  setup_missing: string[]
  income_minor: number
  net_income_minor: number
  rental_income_minor: number
  committed_minor: number
  goal_set_aside_minor: number
  tax_set_aside_minor: number
  buffer_minor: number
  spent_so_far_minor: number
  remaining_minor: number | null
  per_day_remaining_minor: number | null
  period: { start: string | null; end: string | null }
  days_left: number | null
  // Phase 11 provenance: where payday/income came from. 'detected' means
  // inferred from transaction history (show it as a guess to override), null
  // while still in setup. `detected_income` carries the human-readable why.
  payday_source: 'manual' | 'detected' | null
  net_income_source: 'manual' | 'detected' | null
  detected_income: DetectedIncome | null
  committed_items: CommittedItem[]
  goal_items: GoalSetAsideItem[]
}

export interface DetectedIncome {
  label: string
  typical_amount_minor: number
  cadence: string
  median_gap_days: number | null
  occurrences: number
  confidence: number
  last_seen: string
}

export type BenchmarkBand = 'maintainable' | 'average' | 'above_average'

export interface Benchmark {
  band: BenchmarkBand
  band_bounds_minor: [number, number]
  source: string
  as_of: string
  severe: boolean
}

export interface MonthCategory {
  key: string
  label: string
  viz_slot: number | null
  spend_minor: number
  share_pct: number
  avg_3mo_minor: number
  delta_vs_avg_pct: number
  benchmark: Benchmark | null
}

export interface MonthSummary {
  month: string
  income_minor: number
  spend_minor: number
  net_minor: number
  categories: MonthCategory[]
  largest_movers: { key: string; delta_minor: number }[]
  methodology_note: string
  // Phase 12 §5b — which framing produced this breakdown and the exact window
  // it covers. 'calendar' (default) = the calendar month; 'payday' = the
  // current payday-to-payday window (the same one safe-to-spend uses).
  period_mode: 'calendar' | 'payday'
  period: { start: string | null; end: string | null }
  payday_source: 'manual' | 'detected' | null
  setup_missing: string[]
}

export type PeriodMode = 'calendar' | 'payday'

export type TipSeverity = 'info' | 'worth_a_look'

export interface Tip {
  id: number
  rule_key: string
  severity: TipSeverity
  title: string
  body: string
  data: Record<string, unknown>
}

export type RecurringCadence = 'weekly' | 'monthly' | 'quarterly' | 'annual'
// 'not_recurring' (docs/phases/PHASE-10-post-launch-fixes.md item 4): "this
// was never a subscription" (a mortgage standing order, a Starling Space
// transfer) — distinct from 'cancelled' ("this WAS a subscription, I ended
// it"), same dismissed-from-committed-totals backend effect either way.
export type RecurringVerdict = 'keep' | 'cancel_candidate' | 'cancelled' | 'not_recurring'

export interface Recurring {
  id: number | null
  label: string
  cadence: RecurringCadence
  typical_amount_minor: number
  amount_drift_pct: number
  first_seen: string
  last_seen: string
  next_expected: string | null
  occurrences: number
  status: string
  user_verdict: RecurringVerdict | null
  confidence: number
  cancel_candidate: boolean
  monthly_equivalent_minor: number
  old_amount_minor: number
  new_amount_minor: number
}

export interface RecurringList {
  recurring: Recurring[]
  totals: { monthly_committed_minor: number }
}

export interface FinancialConfig {
  payday_day: number | null
  net_monthly_income_minor: number | null
  flat_share_minor: number | null
  buffer_minor: number
  tax_setaside_mode: 'auto' | 'fixed' | 'off'
  tax_setaside_fixed_minor: number | null
  // S4 contractor gap (docs/phases/PHASE-9-personal-goals.md §3) — both
  // tri-state/nullable, NEVER a false default (docs/PRIVATE.md).
  pension_contributing: boolean | null
  fte_conversion_target_date: string | null
}

// ------------------------------------------------------------------------
// Tax — docs/API.md §5 "Tax", semantics governed by docs/TAX.md. Integer
// pence throughout. The estimate is `null` + `missing_inputs` until every
// required tax_config field is answered (docs/TAX.md §0 — never a guessed
// number); a `disclaimer` string is on every response (load-bearing).
// ------------------------------------------------------------------------
export interface TaxConfig {
  monthly_rent_minor: number | null
  letting_agent: string | null
  agent_fee_pct: number | null
  has_mortgage: number | null
  annual_mortgage_interest_minor: number | null
  // Rate + outstanding balance — an honest fallback when the exact
  // certificate figure isn't known (docs/phases/
  // PHASE-10-post-launch-fixes.md item 6); the certificate figure always
  // wins when both are set.
  mortgage_rate_pct: number | null
  mortgage_balance_minor: number | null
  is_leasehold: number | null
  registered_for_sa: number | null
  utr: string | null
  employment_gross_annual_minor: number | null
  field_help: Record<string, string>
}

export type TaxMethod = 'expenses_plus_s24' | 'property_allowance'

export interface TaxRouteExpenses {
  gross_rents_minor: number
  allowable_expenses_minor: number
  loss_brought_forward_minor: number
  profit_minor: number
  tax_on_profit_minor: number
  finance_costs_minor: number
  s24_base_minor: number
  s24_credit_minor: number
  s24_credit_unused_minor: number
  finance_costs_unused_minor: number
  tax_due_minor: number
}

export interface TaxRouteAllowance {
  gross_rents_minor: number
  allowance_minor: number
  profit_minor: number
  tax_on_profit_minor: number
  s24_credit_minor: number
  tax_due_minor: number
}

export interface PaymentsOnAccount {
  required: boolean
  reason: string
  pct_collected_at_source: number
  amounts_minor: number[]
  dates: string[]
}

export interface TaxEstimate {
  method_used: TaxMethod
  tax_due_minor: number
  s24_credit_minor: number
  profit_minor: number
  marginal_band: string
  nic_due_minor: number
  nic_note: string
  loss_brought_forward_minor: number
  payments_on_account: PaymentsOnAccount
  comparison: {
    expenses_plus_s24: TaxRouteExpenses
    property_allowance: TaxRouteAllowance
  }
  assumptions: string[]
  disclaimer: string
}

export interface TaxSummary {
  tax_year: string
  gross_rents_minor: number
  allowable_expenses: Record<string, number>
  allowable_total_minor: number
  finance_costs_minor: number
  capital_improvements_minor: number
  profit_minor: number
  disclaimer: string
  estimate: TaxEstimate | null
  missing_inputs: string[]
}

export type TaxDocType =
  | 'rent_statement'
  | 'agent_invoice'
  | 'mortgage_interest_cert'
  | 'insurance'
  | 'repair_invoice'
  | 'ground_rent'
  | 'other'

export interface TaxDocument {
  id: number
  tax_year: string
  source: string
  doc_type: TaxDocType
  received_at: string
  from_addr: string | null
  subject: string | null
  amount_minor: number | null
  amount_confidence: 'parsed' | 'guessed' | 'none'
  reviewed: boolean
  // Phase 12 — how many rental-ledger rows this document produced. >0 means it
  // has already become tax data (auto-parsed statement, or a human), so the
  // review UI shows "in your ledger" rather than a review action.
  ledger_entry_count: number
  notes: string | null
}

export type LedgerKind = 'income' | 'expense'
export type ExpenseType =
  | 'agent_fees'
  | 'insurance'
  | 'repairs'
  | 'ground_rent_service'
  | 'other_allowable'
  | 'mortgage_interest'
  | 'capital_improvement'

export interface LedgerEntry {
  id: number
  tax_year: string
  local_date: string
  kind: LedgerKind
  expense_type: ExpenseType | null
  amount_minor: number
  source: string
  transaction_id: number | null
  tax_document_id: number | null
  notes: string | null
}

export interface LedgerBody {
  tax_year?: string
  local_date: string
  kind: LedgerKind
  expense_type?: ExpenseType
  amount_minor: number
  source?: string
  transaction_id?: number
  tax_document_id?: number
  notes?: string
}

export interface RentalCandidate {
  transaction_id: number
  local_date: string
  counterparty: string | null
  reference: string | null
  amount_minor: number
  suggested_kind: LedgerKind
  tax_year: string
}

// ------------------------------------------------------------------------
// Deals — docs/API.md §4/§5 "Deals", docs/DESIGN.md §4h, Phase 6. Not a live
// feed: `run` is the newest imported `data/deals/*.json` research file
// (docs/DEPLOYMENT.md §4d), always carrying its own as-of date; `stale` is
// server-computed (>35 days old, docs/engines/deals.py).
// ------------------------------------------------------------------------
export interface DealSource {
  url: string
  fetched_at: string
}

export interface DealRun {
  run_at: string
  sources: DealSource[]
}

export type DealAccess = 'easy' | 'notice' | 'limited_withdrawals'

export interface SavingsDeal {
  id: number
  provider: string
  product: string
  aer_pct: number
  access: DealAccess
  min_deposit_minor: number | null
  fscs: boolean
  is_isa: boolean
  source_url: string
  notes: string | null
}

export interface DealsResponse {
  run: DealRun | null
  deals: SavingsDeal[]
  stale: boolean
}

/** The tax bubble's §3b row-6 glance: profit so far (a ledger fact), the
 * estimate figure or how many inputs it still needs (it never guesses —
 * docs/TAX.md §0), and the unreviewed-documents count. */
export interface TaxGlanceData {
  tax_year: string
  profit_minor: number
  estimated_tax_minor: number | null
  missing_inputs_count: number
  unreviewed_documents: number
}

// ------------------------------------------------------------------------
// Personal wants + gift-occasion budgets — docs/PLAN.md §3 rows 10-11,
// docs/phases/PHASE-9-personal-goals.md §4-5. Both share the affordability
// mechanic (`Affordability`) rather than two separate systems.
// ------------------------------------------------------------------------
export type AffordabilityVerdict = 'unknown' | 'fits_now' | 'not_yet' | 'fits_from_spare_cash'

export interface Affordability {
  verdict: AffordabilityVerdict
  detail: string
}

export interface WantItem {
  id: number
  label: string
  price_minor: number
  bought: boolean
  created_at: string
  /** `null` once bought — no live verdict for something already decided. */
  affordability: Affordability | null
}

export interface WantsList {
  wants: WantItem[]
}

export type OccasionVerdict = 'no_limit_set' | 'under_limit' | 'over_limit'

export interface GiftItem {
  id: number
  occasion_id: number
  label: string
  price_minor: number
  bought: boolean
  bought_date: string | null
}

export interface GiftOccasion {
  id: number
  label: string
  limit_minor: number | null
  target_date: string | null
  items: GiftItem[]
  spent_minor: number
  remaining_minor: number | null
  verdict: OccasionVerdict
}

export interface GiftOccasionsList {
  occasions: GiftOccasion[]
}

/** Every bubble's collapsed glance payload in ONE call — the home screen is
 * a single fetch (docs/phases/PHASE-7-dashboard.md item 6). Each sub-payload
 * is exactly what the matching standalone endpoint returns, built from the
 * same server-side functions. */
export interface BubblesSummary {
  month: string
  safe_to_spend: SafeToSpend
  goals: Goal[]
  month_summary: MonthSummary
  tips_count: number
  recurring: RecurringList
  deals: DealsResponse
  net_worth: NetWorth
  wants: WantsList
  gifts: GiftOccasionsList
  tax: TaxGlanceData
  sync: { runs: SyncRunStatus[] }
}

export const api = {
  base: BASE,
  health: () => get<Health>('/api/health'),
  me: () => get<Me>('/api/auth/me'),
  updateSettings: (patch: UserSettings) => post<{ settings: UserSettings }>('/api/auth/settings', patch, 'PUT'),

  transactions: (filters: TransactionFilters = {}) =>
    get<TransactionsPage>(
      buildQuery('/api/transactions', { ...filters, page: filters.page ?? 1 } as Record<string, string | number | undefined>),
    ),
  patchTransaction: (id: number, patch: TransactionPatch) =>
    post<{ transaction: TransactionItem }>(`/api/transactions/${id}`, patch, 'PATCH'),
  categories: () => get<{ categories: Category[] }>('/api/categories'),
  rules: () => get<{ rules: CategoryRule[] }>('/api/rules'),

  syncStatus: () => get<{ runs: SyncRunStatus[] }>('/api/sync/status'),
  syncRun: (providers?: string[]) =>
    post<{ run_ids: Record<string, number> }>('/api/sync/run', providers ? { providers } : {}),

  accounts: () => get<{ accounts: AccountItem[] }>('/api/accounts'),
  createManualAccount: (body: ManualAccountBody) => post<{ account: AccountItem }>('/api/accounts/manual', body),
  addManualBalance: (accountId: number, body: ManualBalanceBody) =>
    post<{ balance_minor: number; local_date: string }>(`/api/accounts/${accountId}/balance`, body),
  networth: () => get<NetWorth>('/api/networth'),

  goals: () => get<{ goals: Goal[] }>('/api/goals'),
  patchGoal: (key: string, patch: GoalPatch) => post<{ goal: Goal }>(`/api/goals/${key}`, patch, 'PATCH'),

  bubbles: () => get<BubblesSummary>('/api/summary/bubbles'),
  safeToSpend: () => get<SafeToSpend>('/api/summary/safe-to-spend'),
  monthSummary: (month: string, periodMode: PeriodMode = 'calendar') =>
    get<MonthSummary>(buildQuery(`/api/summary/month/${month}`, { period_mode: periodMode })),
  tips: (period?: string) => get<{ tips: Tip[] }>(buildQuery('/api/tips', { period })),
  dismissTip: (id: number) => post<{ dismissed: boolean }>(`/api/tips/${id}/dismiss`, {}),
  recurring: () => get<RecurringList>('/api/recurring'),
  patchRecurring: (id: number, verdict: RecurringVerdict) =>
    post<{ recurring: { id: number; user_verdict: string; status: string } }>(
      `/api/recurring/${id}`,
      { user_verdict: verdict },
      'PATCH',
    ),
  financialConfig: () => get<{ financial_config: FinancialConfig }>('/api/financial-config'),
  putFinancialConfig: (patch: Partial<FinancialConfig>) =>
    post<{ financial_config: FinancialConfig }>('/api/financial-config', patch, 'PUT'),

  taxConfig: () => get<{ config: TaxConfig }>('/api/tax/config'),
  putTaxConfig: (patch: Partial<Omit<TaxConfig, 'field_help'>>) =>
    post<{ config: TaxConfig }>('/api/tax/config', patch, 'PUT'),
  taxSummary: (year: string) => get<TaxSummary>(`/api/tax/years/${year}/summary`),
  taxDocuments: (year?: string, unreviewed?: boolean) =>
    get<{ documents: TaxDocument[] }>(
      buildQuery('/api/tax/documents', { year, unreviewed: unreviewed ? 1 : undefined }),
    ),
  patchTaxDocument: (id: number, patch: { doc_type?: TaxDocType; amount_minor?: number | null; reviewed?: number }) =>
    post<{ document: TaxDocument }>(`/api/tax/documents/${id}`, patch, 'PATCH'),
  taxLedger: (year?: string) => get<{ entries: LedgerEntry[] }>(buildQuery('/api/tax/ledger', { year })),
  addLedgerEntry: (body: LedgerBody) => post<{ entry: LedgerEntry }>('/api/tax/ledger', body),
  deleteLedgerEntry: (id: number) => del<{ deleted: boolean }>(`/api/tax/ledger/${id}`),
  taxCandidates: (year?: string) => get<{ candidates: RentalCandidate[] }>(buildQuery('/api/tax/candidates', { year })),
  taxLedgerCsvUrl: (year: string) => `${BASE}/api/tax/ledger?year=${year}&format=csv`,

  deals: () => get<DealsResponse>('/api/deals'),
  importDeals: () => post<{ imported: number }>('/api/deals/import', {}),

  wants: () => get<WantsList>('/api/wants'),
  createWant: (body: { label: string; price_minor: number }) => post<{ want: WantItem }>('/api/wants', body),
  patchWant: (id: number, patch: { label?: string; price_minor?: number; bought?: boolean }) =>
    post<{ want: WantItem }>(`/api/wants/${id}`, patch, 'PATCH'),
  deleteWant: (id: number) => del<{ deleted: boolean }>(`/api/wants/${id}`),

  giftOccasions: () => get<GiftOccasionsList>('/api/gifts/occasions'),
  createGiftOccasion: (body: { label: string; limit_minor?: number | null; target_date?: string | null }) =>
    post<{ occasion: GiftOccasion }>('/api/gifts/occasions', body),
  patchGiftOccasion: (id: number, patch: { label?: string; limit_minor?: number | null; target_date?: string | null }) =>
    post<{ occasion: GiftOccasion }>(`/api/gifts/occasions/${id}`, patch, 'PATCH'),
  deleteGiftOccasion: (id: number) => del<{ deleted: boolean }>(`/api/gifts/occasions/${id}`),
  createGiftItem: (occasionId: number, body: { label: string; price_minor: number }) =>
    post<{ occasion: GiftOccasion }>(`/api/gifts/occasions/${occasionId}/items`, body),
  patchGiftItem: (id: number, patch: { label?: string; price_minor?: number; bought?: boolean; bought_date?: string | null }) =>
    post<{ occasion: GiftOccasion }>(`/api/gifts/items/${id}`, patch, 'PATCH'),
  deleteGiftItem: (id: number) => del<{ deleted: boolean }>(`/api/gifts/items/${id}`),
  giftItemAffordability: (id: number) => get<Affordability>(`/api/gifts/items/${id}/affordability`),
}

export { ApiError }
