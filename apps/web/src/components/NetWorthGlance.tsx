import type { NetWorth } from '../api'
import { Sparkline } from '../charts/Sparkline'
import { formatMinorWhole, MONEY_CLASS } from '../money'

/** Net Worth bubble's collapsed glance (docs/DESIGN.md §3b row 8): total +
 * a 90-day sparkline + one dot per account (colour-agnostic — a count is
 * the point, not identity, §2c "never colour alone" doesn't apply since
 * nothing here relies on colour to carry meaning). One hero figure plus at
 * most three supporting elements (§3d). */
export function NetWorthGlance({ data }: { data: NetWorth }) {
  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>{formatMinorWhole(data.total_minor)}</span>
      <div className="flex w-full items-center gap-2">
        <Sparkline series={data.series.map((p) => ({ date: p.date, value_minor: p.total_minor }))} width={96} height={20} className="min-w-0 flex-1" />
        <span className="shrink-0 font-mono text-[10px] text-ink-soft">90d</span>
      </div>
      {data.by_account.length > 0 && (
        <div className="flex items-center gap-1" aria-hidden>
          {data.by_account.map((account) => (
            <span key={account.account_id} className="h-1.5 w-1.5 rounded-full bg-viz-5" title={account.name} />
          ))}
        </div>
      )}
    </>
  )
}
