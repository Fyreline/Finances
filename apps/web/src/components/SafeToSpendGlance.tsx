import type { SafeToSpend } from '../api'
import { safeToSpendSegments, WaterfallStrip } from '../charts/WaterfallStrip'
import { useCountUpMinor } from '../hooks/useCountUp'
import { formatMinor, MONEY_CLASS } from '../money'

/** Hero bubble's collapsed glance (docs/DESIGN.md §3b row 1): the safe-to-spend
 * figure (38px mono, the app's one count-up — §1), a `£X/day · N days left`
 * sub-line, and the waterfall strip rendered small + unlabelled. Returns null
 * in the setup-missing state so the bubble falls back to its serif setup line. */
export function SafeToSpendGlance({ data }: { data: SafeToSpend }) {
  const safe = data.safe_to_spend_minor ?? 0
  const animated = useCountUpMinor(safe)
  if (data.safe_to_spend_minor === null) return null
  const perDay = data.per_day_remaining_minor ?? 0
  return (
    <>
      <span className={`text-[38px] leading-none ${MONEY_CLASS} ${safe < 0 ? 'text-over' : 'text-ink'}`}>
        {formatMinor(animated)}
      </span>
      <span className="font-mono text-[11px] text-ink-soft">
        {formatMinor(perDay)}/day · {data.days_left ?? 0} days left
      </span>
      <WaterfallStrip
        segments={safeToSpendSegments(data)}
        totalMinor={data.income_minor}
        height={8}
        showLegend={false}
      />
    </>
  )
}
