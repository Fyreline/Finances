import { useEffect, useState } from 'react'
import { api, type Recurring, type RecurringVerdict } from '../../api'
import { formatMinor, MONEY_CLASS } from '../../money'

const CADENCE_GLYPH: Record<string, string> = { monthly: '↻', weekly: '↻', quarterly: '↻', annual: '↻' }

function monthYear(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
}

function ConfidenceDots({ confidence }: { confidence: number }) {
  const filled = confidence >= 0.8 ? 3 : confidence >= 0.6 ? 2 : 1
  return (
    <span className="inline-flex items-center gap-0.5" title={`confidence ${Math.round(confidence * 100)}%`}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={`inline-block h-1.5 w-1.5 rounded-full ${i < filled ? 'bg-ink-mid' : 'bg-line-strong'}`}
          aria-hidden
        />
      ))}
    </span>
  )
}

function RecurringRow({ item, onVerdict }: { item: Recurring; onVerdict: (id: number, v: RecurringVerdict) => void }) {
  // Both dismissing verdicts dim the row identically — only the label the
  // user picked differs, not the visual treatment
  // (docs/phases/PHASE-10-post-launch-fixes.md item 4).
  const isDismissed = item.user_verdict === 'cancelled' || item.user_verdict === 'not_recurring'
  return (
    <div className={`py-3 ${isDismissed ? 'opacity-50' : ''}`}>
      <div className="flex items-center gap-2">
        <span className="font-mono text-ink-soft" aria-hidden>
          {CADENCE_GLYPH[item.cadence] ?? '↻'}
        </span>
        <span className="flex-1 truncate text-[14px] text-ink">{item.label}</span>
        <span className={`text-[14px] ${MONEY_CLASS} text-ink`}>{formatMinor(Math.abs(item.typical_amount_minor))}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-6 font-mono text-[11px] text-ink-soft">
        <span>{item.cadence}</span>
        {item.cadence !== 'monthly' && <span>≈ {formatMinor(Math.abs(item.monthly_equivalent_minor))}/mo</span>}
        {item.next_expected && <span>next {monthYear(item.next_expected)}</span>}
        <span>
          since {monthYear(item.first_seen)} · {item.occurrences} payments
        </span>
        <ConfidenceDots confidence={item.confidence} />
        {item.confidence < 0.6 && <span className="text-ink-soft">possibly recurring</span>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 pl-6">
        {item.amount_drift_pct >= 10 && (
          <span
            className="rounded-full bg-kraft/20 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-clay-deep"
            title={`${formatMinor(Math.abs(item.old_amount_minor))} → ${formatMinor(Math.abs(item.new_amount_minor))}`}
          >
            price rise
          </span>
        )}
        {item.cancel_candidate && !isDismissed && (
          <span className="rounded-full bg-oat px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-mid">
            still using this?
          </span>
        )}
        {item.id !== null && !isDismissed && (
          <span className="ml-auto flex gap-1">
            <button
              type="button"
              onClick={() => onVerdict(item.id as number, 'keep')}
              className={`rounded-md border border-line px-2 py-0.5 text-[11px] transition hover:bg-paper-deep ${
                item.user_verdict === 'keep' ? 'bg-olive/15 text-olive' : 'text-ink-mid'
              }`}
            >
              keep
            </button>
            <button
              type="button"
              onClick={() => onVerdict(item.id as number, 'cancelled')}
              className="rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-mid transition hover:bg-paper-deep"
              title="A real subscription you decided to end (Netflix, gym, etc.)"
            >
              cancelled
            </button>
            <button
              type="button"
              onClick={() => onVerdict(item.id as number, 'not_recurring')}
              className="rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-mid transition hover:bg-paper-deep"
              title="This was never a subscription — a mortgage payment, a savings transfer, etc."
            >
              not a subscription
            </button>
          </span>
        )}
      </div>
    </div>
  )
}

/** RecurringList (docs/DESIGN.md §4f) — detected recurring payments with
 * cadence, confidence, gentle price-rise and cancel-candidate flags, and
 * keep/cancelled actions. Copy never asserts non-usage (DATA_MODEL §3a.4). */
export function RecurringDetail() {
  const [items, setItems] = useState<Recurring[] | null>(null)
  const [committed, setCommitted] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .recurring()
      .then((r) => {
        setItems(r.recurring)
        setCommitted(r.totals.monthly_committed_minor)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load"))
  }
  useEffect(load, [])

  async function onVerdict(id: number, verdict: RecurringVerdict) {
    await api.patchRecurring(id, verdict)
    load()
  }

  if (error) return <p className="text-[13px] text-ink-mid">{error}</p>
  if (!items) return <p className="font-mono text-[11px] text-ink-soft">Loading…</p>
  if (items.length === 0) {
    return <p className="font-serif text-[15px] text-ink-mid">No recurring payments detected yet.</p>
  }

  return (
    <div className="space-y-2">
      <div className="divide-y divide-line">
        {items.map((item) => (
          <RecurringRow key={`${item.label}-${item.cadence}`} item={item} onVerdict={onVerdict} />
        ))}
      </div>
      <div className="flex items-baseline justify-between border-t border-line pt-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Monthly committed</span>
        <span className={`text-[15px] ${MONEY_CLASS} text-ink`}>{formatMinor(committed)}/mo</span>
      </div>
    </div>
  )
}
