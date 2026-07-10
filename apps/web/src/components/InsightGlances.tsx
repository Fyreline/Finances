import type { MonthSummary, RecurringList, TaxGlanceData } from '../api'
import { categoryChipClass } from '../categoryColor'
import { BENCHMARK_LABEL } from '../charts/verdict'
import { formatMinor, formatMinorWhole, MONEY_CLASS } from '../money'

/** Spending bubble glance (docs/DESIGN.md §3b row 4): month total, top-3
 * category chips with amounts, the worst verdict pill (named — "eating out ·
 * above average", never colour alone, §2c.2), and a tips count chip. */
export function SpendingGlance({ summary, tipCount }: { summary: MonthSummary; tipCount: number }) {
  const top3 = summary.categories.slice(0, 3)
  const worst = summary.categories.find((c) => c.benchmark?.band === 'above_average') ?? null
  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>{formatMinor(summary.spend_minor)}</span>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {top3.map((c) => (
          <span key={c.key} className="flex items-center gap-1 font-mono text-[11px] text-ink-soft">
            <span className={`inline-block h-2 w-2 rounded-sm ${categoryChipClass(c.viz_slot)}`} aria-hidden />
            {c.label.toLowerCase()} <span className={`${MONEY_CLASS} text-ink-mid`}>{formatMinor(c.spend_minor)}</span>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {worst?.benchmark && (
          <span className="rounded-full bg-kraft/20 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-clay-deep">
            {worst.label.toLowerCase()} · {BENCHMARK_LABEL[worst.benchmark.band]}
          </span>
        )}
        {tipCount > 0 && (
          <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-soft">
            {tipCount} {tipCount === 1 ? 'tip' : 'tips'}
          </span>
        )}
      </div>
    </>
  )
}

/** Recurring bubble glance (docs/DESIGN.md §3b row 5): `£214.50/mo
 * committed`, a worth-a-look count, and the next-due line (`Netflix · 3 Aug`). */
export function RecurringGlance({ data }: { data: RecurringList }) {
  const worthLook = data.recurring.filter((r) => r.cancel_candidate && r.user_verdict !== 'cancelled').length
  const next = data.recurring
    .filter((r) => r.next_expected && r.user_verdict !== 'cancelled')
    .sort((a, b) => (a.next_expected! < b.next_expected! ? -1 : 1))[0]
  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>
        {formatMinor(data.totals.monthly_committed_minor)}/mo{' '}
        <span className="font-sans text-sm text-ink-soft">committed</span>
      </span>
      {worthLook > 0 && (
        <span className="rounded-full bg-oat px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-mid">
          {worthLook} worth a look
        </span>
      )}
      {next && (
        <span className="font-mono text-[11px] text-ink-soft">
          {next.label} ·{' '}
          {new Date(`${next.next_expected}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
        </span>
      )}
    </>
  )
}

/** Tax bubble glance (docs/DESIGN.md §3b row 6): profit so far (a ledger
 * fact), `est. tax £Y` — or, while inputs are missing, a quiet `oat` pill
 * saying how many it still needs (the estimator never guesses, docs/TAX.md
 * §0) — and the unreviewed-documents count. */
export function TaxGlance({ data }: { data: TaxGlanceData }) {
  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>
        {formatMinorWhole(data.profit_minor)} <span className="font-sans text-sm text-ink-soft">profit so far</span>
      </span>
      <div className="flex flex-wrap items-center gap-2">
        {data.estimated_tax_minor !== null ? (
          <span className={`font-mono text-[11px] ${MONEY_CLASS} text-ink-mid`}>
            est. tax {formatMinor(data.estimated_tax_minor)}
          </span>
        ) : (
          <span className="rounded-full bg-oat px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-mid">
            estimate needs {data.missing_inputs_count} {data.missing_inputs_count === 1 ? 'input' : 'inputs'}
          </span>
        )}
      </div>
      {data.unreviewed_documents > 0 && (
        <span className="font-mono text-[11px] text-ink-soft">
          {data.unreviewed_documents} {data.unreviewed_documents === 1 ? 'document' : 'documents'} to review
        </span>
      )}
    </>
  )
}
