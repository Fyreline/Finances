import type { DealsResponse } from '../api'
import { MONEY_CLASS } from '../money'

function checkedDateLabel(runAt: string): string {
  return new Date(runAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** Savings-deals bubble's collapsed glance (docs/DESIGN.md §3b row 7): best
 * researched rate + provider + the "checked <date>" line — always visible,
 * never a live-feed implication (docs/API.md §4). */
export function DealsGlance({ data }: { data: DealsResponse }) {
  if (!data.run || data.deals.length === 0) return null
  const best = data.deals.reduce((a, b) => (b.aer_pct > a.aer_pct ? b : a))
  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>{best.aer_pct.toFixed(2)}% AER</span>
      <span className="font-mono text-[11px] text-ink-soft">{best.provider}</span>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-ink-soft">checked {checkedDateLabel(data.run.run_at)}</span>
        {data.stale && (
          <span className="rounded-full bg-oat px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-mid">
            stale
          </span>
        )}
      </div>
    </>
  )
}
