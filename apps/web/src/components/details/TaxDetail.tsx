import { type ReactNode, useCallback, useEffect, useState } from 'react'
import {
  api,
  type LedgerBody,
  type LedgerEntry,
  type TaxConfig,
  type TaxDocType,
  type TaxDocument,
  type TaxEstimate,
  type TaxSummary,
} from '../../api'
import { formatMinor, MONEY_CLASS } from '../../money'

// The bubble shows the CURRENT tax year (docs/DESIGN.md §3b row 6, docs/
// TAX.md §1) — computed, not hardcoded, so the detail doesn't silently show
// a stale year after 5 April. Mirrors the server's `dates.tax_year_of`
// (6 April starts the new year — the statutory boundary).
function currentTaxYear(now = new Date()): string {
  const m = now.getMonth() + 1
  const d = now.getDate()
  const startYear = m > 4 || (m === 4 && d >= 6) ? now.getFullYear() : now.getFullYear() - 1
  return `${startYear}-${String((startYear + 1) % 100).padStart(2, '0')}`
}
const TAX_YEAR = currentTaxYear()

type Tab = 'documents' | 'ledger' | 'estimate'
const TABS: { key: Tab; label: string }[] = [
  { key: 'documents', label: 'Documents' },
  { key: 'ledger', label: 'Ledger' },
  { key: 'estimate', label: 'Estimate' },
]

/** Internal tabs as a hash segment (`#tax/estimate`) — docs/DESIGN.md §3c,
 * same contract as SpendingDetail. */
function useTabHash(defaultTab: Tab): [Tab, (tab: Tab) => void] {
  const parse = (): Tab => {
    const raw = window.location.hash.replace(/^#/, '').split('/')[1]
    return (TABS.some((t) => t.key === raw) ? raw : defaultTab) as Tab
  }
  const [tab, setTabState] = useState<Tab>(parse)
  useEffect(() => {
    const onHash = () => setTabState(parse())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const setTab = (next: Tab) => {
    const bubbleKey = window.location.hash.replace(/^#/, '').split('/')[0] || 'tax'
    window.location.hash = `${bubbleKey}/${next}`
    setTabState(next)
  }
  return [tab, setTab]
}

/** The load-bearing disclaimer (docs/TAX.md §0, docs/DESIGN.md §4g) — renders
 * on every tax surface, non-dismissable, styled warmly and worded absolutely. */
export function TaxDisclaimer() {
  return (
    <div className="rounded-md bg-oat p-3 text-ink-mid">
      <p className="font-serif text-sm text-ink">Kakeibo estimates for planning; it is not tax advice.</p>
      <p className="mt-1 text-[12px]">
        Numbers here must be checked against HMRC's own calculators or an accountant before filing.
      </p>
    </div>
  )
}

const EXPENSE_LABELS: Record<string, string> = {
  agent_fees: 'Agent fees',
  insurance: 'Insurance',
  repairs: 'Repairs & maintenance',
  ground_rent_service: 'Ground rent / service charge',
  other_allowable: 'Other allowable',
  mortgage_interest: 'Mortgage interest (S24 credit, not a deduction)',
  capital_improvement: 'Capital improvement (CGT memo, not allowable)',
}

const DOC_TYPE_LABELS: Record<TaxDocType, string> = {
  rent_statement: 'Rent statement',
  agent_invoice: 'Agent invoice',
  mortgage_interest_cert: 'Mortgage interest certificate',
  insurance: 'Insurance',
  repair_invoice: 'Repair invoice',
  ground_rent: 'Ground rent',
  other: 'Other',
}

function Money({ minor }: { minor: number }) {
  return <span className={MONEY_CLASS}>{formatMinor(minor)}</span>
}

// ------------------------------------------------------------------ Estimate
function Line({ label, minor, muted }: { label: string; minor: number; muted?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-4 py-0.5 ${muted ? 'text-ink-soft' : 'text-ink'}`}>
      <span className="text-[13px]">{label}</span>
      <Money minor={minor} />
    </div>
  )
}

function RouteCard({
  title,
  winner,
  children,
  taxDue,
}: {
  title: string
  winner: boolean
  taxDue: number
  children: ReactNode
}) {
  return (
    <div className={`flex-1 rounded-lg border p-4 ${winner ? 'border-olive' : 'border-line'}`}>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="font-display text-sm font-medium text-ink">{title}</h4>
        {winner && (
          <span className="rounded-full bg-olive/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-olive">
            better
          </span>
        )}
      </div>
      <div className="space-y-0.5">{children}</div>
      <div className="mt-2 flex items-baseline justify-between border-t border-line pt-2">
        <span className="text-[13px] font-medium text-ink">Tax due</span>
        <span className={`${MONEY_CLASS} text-base font-medium ${winner ? 'text-olive' : 'text-ink'}`}>
          {formatMinor(taxDue)}
        </span>
      </div>
    </div>
  )
}

/** The SA deadline checklist for the first rental year (docs/TAX.md §6). The
 * 5 Oct 2026 registration nudge fires while SA registration is unconfirmed
 * (registered_for_sa ∈ {null, 0}) — the one place allowed a crimson callout
 * (docs/DESIGN.md §4g), a real statutory deadline. */
function DeadlineChecklist({ registered }: { registered: number | null }) {
  const needsRegistration = registered === null || registered === 0
  return (
    <div className="space-y-2">
      <h4 className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
        Self Assessment deadlines — first rental year 2025-26
      </h4>
      {needsRegistration && (
        <div className="rounded-md border border-clay/60 bg-clay/5 p-3">
          <p className="font-serif text-sm text-ink">Register for Self Assessment by 5 October 2026.</p>
          <p className="mt-1 text-[12px] text-ink-mid">
            The 2025-26 rental year is your first Self Assessment year. If you are not already registered, the
            statutory deadline to register is 5 October 2026 — HMRC then issues a UTR. Confirm your registration
            status in the setup to clear this reminder.
          </p>
        </div>
      )}
      <ul className="space-y-1 text-[13px] text-ink-mid">
        <li className="flex justify-between gap-4">
          <span>Register for SA (if not already)</span>
          <span className="font-mono text-ink">5 Oct 2026</span>
        </li>
        <li className="flex justify-between gap-4">
          <span>File online + pay 2025-26</span>
          <span className="font-mono text-ink">31 Jan 2027</span>
        </li>
        <li className="flex justify-between gap-4 text-ink-soft">
          <span>Online deadline to collect via PAYE code (bill &lt; £3,000)</span>
          <span className="font-mono">30 Dec 2026</span>
        </li>
        <li className="flex justify-between gap-4">
          <span>Second payment on account (if applicable)</span>
          <span className="font-mono text-ink">31 Jul 2027</span>
        </li>
      </ul>
    </div>
  )
}

function EstimatePanel({ estimate }: { estimate: TaxEstimate }) {
  const exp = estimate.comparison.expenses_plus_s24
  const allow = estimate.comparison.property_allowance
  const expWins = estimate.method_used === 'expenses_plus_s24'
  const poa = estimate.payments_on_account

  return (
    <div className="space-y-4">
      {estimate.assumptions.length > 0 && (
        <div className="rounded-md bg-oat/60 p-2 text-[12px] text-ink-mid">
          {estimate.assumptions.map((a) => (
            <p key={a}>Assumption: {a}</p>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row">
        <RouteCard title="Actual expenses + S24 credit" winner={expWins} taxDue={exp.tax_due_minor}>
          <Line label="Gross rents" minor={exp.gross_rents_minor} />
          <Line label="Allowable expenses" minor={-exp.allowable_expenses_minor} muted />
          {exp.loss_brought_forward_minor > 0 && (
            <Line label="Loss brought forward" minor={-exp.loss_brought_forward_minor} muted />
          )}
          <Line label="Taxable profit" minor={exp.profit_minor} />
          <Line label="Tax on profit" minor={exp.tax_on_profit_minor} muted />
          <Line label="Section 24 credit (20%)" minor={-exp.s24_credit_minor} muted />
        </RouteCard>

        <RouteCard title="£1,000 property allowance" winner={!expWins} taxDue={allow.tax_due_minor}>
          <Line label="Gross rents" minor={allow.gross_rents_minor} />
          <Line label="Property allowance" minor={-allow.allowance_minor} muted />
          <Line label="Taxable profit" minor={allow.profit_minor} />
          <Line label="Tax on profit" minor={allow.tax_on_profit_minor} muted />
          <Line label="No expenses / no S24 credit" minor={0} muted />
        </RouteCard>
      </div>

      <div className="rounded-lg border border-line p-4">
        <div className="flex items-baseline justify-between">
          <span className="text-[13px] text-ink-mid">Estimated tax due ({estimate.marginal_band} band)</span>
          <span className={`${MONEY_CLASS} text-lg font-medium text-ink`}>{formatMinor(estimate.tax_due_minor)}</span>
        </div>
        <div className="mt-2 space-y-1 text-[12px] text-ink-soft">
          <p>National Insurance: {estimate.nic_note}</p>
          <p>
            Payments on account:{' '}
            {poa.required
              ? `required — ${poa.amounts_minor.map((m) => formatMinor(m)).join(' + ')} on ${poa.dates.join(' & ')}`
              : poa.reason}
          </p>
        </div>
      </div>

      <TaxDisclaimer />
    </div>
  )
}

// ------------------------------------------------------------------- Config
type FlagField = 'has_mortgage' | 'is_leasehold' | 'registered_for_sa'
type MoneyField = 'annual_mortgage_interest_minor' | 'employment_gross_annual_minor' | 'monthly_rent_minor'

function ConfigForm({ config, onSaved }: { config: TaxConfig; onSaved: (c: TaxConfig) => void }) {
  const [draft, setDraft] = useState(config)
  const [saving, setSaving] = useState(false)

  const setFlag = (field: FlagField, value: number | null) => setDraft({ ...draft, [field]: value })
  const setMoney = (field: MoneyField, pounds: string) =>
    setDraft({ ...draft, [field]: pounds === '' ? null : Math.round(parseFloat(pounds) * 100) })

  const save = async () => {
    setSaving(true)
    try {
      const res = await api.putTaxConfig({
        has_mortgage: draft.has_mortgage,
        annual_mortgage_interest_minor: draft.annual_mortgage_interest_minor,
        is_leasehold: draft.is_leasehold,
        registered_for_sa: draft.registered_for_sa,
        utr: draft.utr,
        employment_gross_annual_minor: draft.employment_gross_annual_minor,
        monthly_rent_minor: draft.monthly_rent_minor,
        letting_agent: draft.letting_agent,
        agent_fee_pct: draft.agent_fee_pct,
      })
      onSaved(res.config)
    } finally {
      setSaving(false)
    }
  }

  const help = config.field_help
  const poundsValue = (minor: number | null) => (minor === null ? '' : (minor / 100).toString())

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <label className="text-[13px] font-medium text-ink">Is there a mortgage on the rented house?</label>
          <div className="flex gap-1">
            {([
              [1, 'Yes'],
              [0, 'No'],
            ] as [number, string][]).map(([v, l]) => (
              <button
                key={l}
                type="button"
                onClick={() => setFlag('has_mortgage', v)}
                className={`rounded-md border px-3 py-1 font-mono text-[11px] ${
                  draft.has_mortgage === v ? 'border-clay text-ink' : 'border-line text-ink-soft'
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <p className="text-[12px] text-ink-soft">{help.has_mortgage}</p>
      </div>

      {draft.has_mortgage === 1 && (
        <FieldMoney
          label="Annual mortgage interest (£)"
          help={help.annual_mortgage_interest_minor}
          value={poundsValue(draft.annual_mortgage_interest_minor)}
          onChange={(v) => setMoney('annual_mortgage_interest_minor', v)}
        />
      )}

      <FieldMoney
        label="Employment gross annual (£)"
        help={help.employment_gross_annual_minor}
        value={poundsValue(draft.employment_gross_annual_minor)}
        onChange={(v) => setMoney('employment_gross_annual_minor', v)}
      />

      <div className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <label className="text-[13px] font-medium text-ink">Registered for Self Assessment?</label>
          <div className="flex gap-1">
            {([
              [1, 'Yes'],
              [0, 'No'],
            ] as [number, string][]).map(([v, l]) => (
              <button
                key={l}
                type="button"
                onClick={() => setFlag('registered_for_sa', v)}
                className={`rounded-md border px-3 py-1 font-mono text-[11px] ${
                  draft.registered_for_sa === v ? 'border-clay text-ink' : 'border-line text-ink-soft'
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <p className="text-[12px] text-ink-soft">{help.registered_for_sa}</p>
      </div>

      <div className="space-y-1">
        <div className="flex items-center justify-between gap-4">
          <label className="text-[13px] font-medium text-ink">Is the property leasehold?</label>
          <div className="flex gap-1">
            {([
              [1, 'Yes'],
              [0, 'No'],
            ] as [number, string][]).map(([v, l]) => (
              <button
                key={l}
                type="button"
                onClick={() => setFlag('is_leasehold', v)}
                className={`rounded-md border px-3 py-1 font-mono text-[11px] ${
                  draft.is_leasehold === v ? 'border-clay text-ink' : 'border-line text-ink-soft'
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <p className="text-[12px] text-ink-soft">{help.is_leasehold}</p>
      </div>

      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="rounded-md border border-line-strong px-4 py-1.5 font-mono text-[12px] text-ink hover:border-clay disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save setup'}
      </button>
    </div>
  )
}

function FieldMoney({
  label,
  help,
  value,
  onChange,
}: {
  label: string
  help: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-4">
        <label className="text-[13px] font-medium text-ink">{label}</label>
        <input
          type="number"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-36 rounded-md border border-line bg-paper px-2 py-1 text-right font-mono text-[13px] text-ink"
        />
      </div>
      <p className="text-[12px] text-ink-soft">{help}</p>
    </div>
  )
}

function MissingInputsCard({ missing }: { missing: string[] }) {
  const labels: Record<string, string> = {
    has_mortgage: 'whether the rented house has a mortgage',
    annual_mortgage_interest: 'the annual mortgage interest',
    employment_gross_annual: 'employment gross annual pay',
  }
  return (
    <div className="max-w-2xl space-y-2">
      <p className="font-serif text-base text-ink-mid">
        The estimate needs {missing.length} {missing.length === 1 ? 'input' : 'inputs'} before it can show a number —
        Kakeibo never guesses a tax figure.
      </p>
      <ul className="list-disc pl-5 text-[13px] text-ink-mid">
        {missing.map((m) => (
          <li key={m}>{labels[m] ?? m}</li>
        ))}
      </ul>
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Fill these in below</p>
    </div>
  )
}

// ---------------------------------------------------------------- Documents
function DocumentsPanel() {
  const [docs, setDocs] = useState<TaxDocument[] | null>(null)
  const load = useCallback(() => {
    api.taxDocuments(TAX_YEAR).then((r) => setDocs(r.documents), () => setDocs([]))
  }, [])
  useEffect(load, [load])

  const review = async (d: TaxDocument) => {
    await api.patchTaxDocument(d.id, { reviewed: d.reviewed ? 0 : 1 })
    load()
  }

  if (docs === null) return <p className="text-[13px] text-ink-soft">Loading…</p>
  if (docs.length === 0)
    return (
      <p className="font-serif text-base text-ink-mid">
        No rental documents pulled yet. Once Gmail is connected, statements, certificates and invoices land here for
        review before anything reaches the ledger.
      </p>
    )

  return (
    <div className="space-y-2">
      {docs.map((d) => (
        <div key={d.id} className="flex items-center justify-between gap-3 rounded-md border border-line p-3">
          <div className="min-w-0">
            <p className="truncate text-[13px] text-ink">{d.subject ?? DOC_TYPE_LABELS[d.doc_type]}</p>
            <p className="truncate font-mono text-[11px] text-ink-soft">
              {d.received_at} · {DOC_TYPE_LABELS[d.doc_type]} · {d.from_addr ?? '—'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className={MONEY_CLASS}>{d.amount_minor === null ? '—' : formatMinor(d.amount_minor)}</span>
            <button
              type="button"
              onClick={() => review(d)}
              className={`rounded-full px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.08em] ${
                d.reviewed ? 'bg-olive/15 text-olive' : 'bg-oat text-ink-mid'
              }`}
            >
              {d.reviewed ? 'reviewed' : 'review'}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------- Ledger
function LedgerPanel() {
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null)
  const [form, setForm] = useState<{ local_date: string; kind: 'income' | 'expense'; expense_type: string; amount: string }>(
    { local_date: '', kind: 'income', expense_type: 'agent_fees', amount: '' },
  )
  const load = useCallback(() => {
    api.taxLedger(TAX_YEAR).then((r) => setEntries(r.entries), () => setEntries([]))
  }, [])
  useEffect(load, [load])

  const add = async () => {
    if (!form.local_date || form.amount === '') return
    const body: LedgerBody = {
      tax_year: TAX_YEAR,
      local_date: form.local_date,
      kind: form.kind,
      amount_minor: Math.round(parseFloat(form.amount) * 100),
      ...(form.kind === 'expense' ? { expense_type: form.expense_type as LedgerBody['expense_type'] } : {}),
    }
    await api.addLedgerEntry(body)
    setForm({ ...form, amount: '', local_date: '' })
    load()
  }
  const remove = async (id: number) => {
    await api.deleteLedgerEntry(id)
    load()
  }

  const income = (entries ?? []).filter((e) => e.kind === 'income')
  const expenses = (entries ?? []).filter((e) => e.kind === 'expense')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2 rounded-md border border-line p-3">
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-soft">Date</span>
          <input
            type="date"
            value={form.local_date}
            onChange={(e) => setForm({ ...form, local_date: e.target.value })}
            className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-[12px] text-ink"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-soft">Kind</span>
          <select
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value as 'income' | 'expense' })}
            className="rounded-md border border-line bg-paper px-2 py-1 text-[12px] text-ink"
          >
            <option value="income">Income</option>
            <option value="expense">Expense</option>
          </select>
        </label>
        {form.kind === 'expense' && (
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-soft">Type</span>
            <select
              value={form.expense_type}
              onChange={(e) => setForm({ ...form, expense_type: e.target.value })}
              className="rounded-md border border-line bg-paper px-2 py-1 text-[12px] text-ink"
            >
              {Object.entries(EXPENSE_LABELS).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-soft">Amount (£)</span>
          <input
            type="number"
            inputMode="decimal"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            className="w-28 rounded-md border border-line bg-paper px-2 py-1 text-right font-mono text-[12px] text-ink"
          />
        </label>
        <button
          type="button"
          onClick={add}
          className="rounded-md border border-line-strong px-3 py-1.5 font-mono text-[12px] text-ink hover:border-clay"
        >
          Add
        </button>
        <a
          href={api.taxLedgerCsvUrl(TAX_YEAR)}
          className="ml-auto font-mono text-[11px] text-clay underline"
        >
          Export CSV
        </a>
      </div>

      <LedgerGroup title="Income" entries={income} onRemove={remove} />
      <LedgerGroup title="Expenses" entries={expenses} onRemove={remove} />
      {entries !== null && entries.length === 0 && (
        <p className="font-serif text-base text-ink-mid">
          The ledger is empty. Add rent received and allowable expenses above, or add reviewed documents from the
          Documents tab.
        </p>
      )}
    </div>
  )
}

function LedgerGroup({
  title,
  entries,
  onRemove,
}: {
  title: string
  entries: LedgerEntry[]
  onRemove: (id: number) => void
}) {
  if (entries.length === 0) return null
  return (
    <div>
      <h4 className="mb-1 font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">{title}</h4>
      <div className="divide-y divide-line">
        {entries.map((e) => (
          <div key={e.id} className="flex items-center justify-between gap-3 py-1.5">
            <span className="font-mono text-[11px] text-ink-soft">{e.local_date}</span>
            <span className="flex-1 truncate text-[13px] text-ink">
              {e.expense_type ? EXPENSE_LABELS[e.expense_type] : 'Rent received'}
            </span>
            <Money minor={e.kind === 'income' ? e.amount_minor : -e.amount_minor} />
            <button
              type="button"
              onClick={() => onRemove(e.id)}
              className="font-mono text-[11px] text-ink-soft hover:text-clay"
              aria-label="Remove entry"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// -------------------------------------------------------------------- Shell
export function TaxDetail() {
  const [tab, setTab] = useTabHash('estimate')
  const [summary, setSummary] = useState<TaxSummary | null>(null)
  const [config, setConfig] = useState<TaxConfig | null>(null)

  const load = useCallback(() => {
    api.taxSummary(TAX_YEAR).then(setSummary, () => setSummary(null))
    api.taxConfig().then((r) => setConfig(r.config), () => setConfig(null))
  }, [])
  useEffect(load, [load])

  return (
    <div className="space-y-4">
      {/* The surface states its own window (docs/DESIGN.md §2c.6) — every
          figure below (profit, estimate, ledger) is for this one tax year. */}
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">TAX YEAR {TAX_YEAR}</p>
      <TaxDisclaimer />

      <div role="tablist" aria-label="Tax views" className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60 ${
              tab === t.key ? 'border-b-2 border-clay text-ink' : 'text-ink-soft hover:text-ink-mid'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'documents' && <DocumentsPanel />}
      {tab === 'ledger' && <LedgerPanel />}
      {tab === 'estimate' && (
        <div className="space-y-5">
          {summary?.estimate ? (
            <EstimatePanel estimate={summary.estimate} />
          ) : (
            <MissingInputsCard missing={summary?.missing_inputs ?? []} />
          )}
          <DeadlineChecklist registered={config?.registered_for_sa ?? null} />
          {config && (
            <div className="border-t border-line pt-4">
              <h4 className="mb-3 font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Setup</h4>
              <ConfigForm
                config={config}
                onSaved={(c) => {
                  setConfig(c)
                  load()
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
