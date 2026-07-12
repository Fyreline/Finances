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
  // Spending has actually exceeded the safe-to-spend allowance (remaining <
  // 0) once real spend-so-far is accounted for — the headline clamps to £0
  // rather than showing the flat allowance as if nothing had been spent, per
  // the household's "crimson as information, never guessed" rule (§2a);
  // `overBy` is the small, honest "how much" that goes with it.
  const remaining = data.remaining_minor ?? safe
  const overBy = remaining < 0 ? -remaining : 0
  const animated = useCountUpMinor(overBy > 0 ? 0 : safe)
  if (data.safe_to_spend_minor === null) return null
  const perDay = data.per_day_remaining_minor ?? 0
  return (
    <>
      <span className="flex items-baseline gap-2">
        <span className={`text-[38px] leading-none ${MONEY_CLASS} ${overBy > 0 ? 'text-over' : 'text-ink'}`}>
          {formatMinor(overBy > 0 ? 0 : animated)}
        </span>
        {overBy > 0 && (
          <span className={`font-mono text-[11px] ${MONEY_CLASS} text-over`}>over by {formatMinor(overBy)}</span>
        )}
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
