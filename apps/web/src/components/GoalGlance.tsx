import type { Goal } from '../api'
import { GOAL_VERDICT_LABEL, GOAL_VERDICT_STYLE } from '../charts/verdict'
import { shapeGoalBar } from '../charts/shape'
import { Sparkline } from '../charts/Sparkline'
import { useBarFill } from '../charts/useBarFill'
import { formatMinorSigned, formatMinorWhole, formatPercent, MONEY_CLASS } from '../money'

/** House deposit bubble's collapsed glance (docs/DESIGN.md §3b row 2):
 * progress bar + verdict pill + target date. One hero figure, at most
 * three supporting elements (§3d) — never shown until a real goal with a
 * target exists (`DepositDetail`/`HomePage` fall back to the setup-state
 * lines otherwise). */
export function DepositGlance({ goal }: { goal: Goal }) {
  const { fillPct } = shapeGoalBar(goal.current_minor, goal.target_minor, goal.projected_at_target_minor)
  const fillWidth = useBarFill(fillPct * 100)
  if (goal.target_minor === null || goal.target_date === null) return null
  const targetLabel = new Date(`${goal.target_date}T00:00:00`)
    .toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    .toUpperCase()

  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>{formatMinorWhole(goal.current_minor)}</span>
      <div className="h-1.5 w-full rounded-full bg-paper-deep" aria-hidden>
        <div
          className="h-1.5 rounded-full bg-setaside motion-safe:transition-[width] motion-safe:duration-500"
          style={{ width: `${fillWidth.toFixed(1)}%` }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] ${GOAL_VERDICT_STYLE[goal.status]}`}
        >
          {GOAL_VERDICT_LABEL[goal.status]}
        </span>
        <span className="font-mono text-[11px] text-ink-soft">
          {formatPercent(fillPct)} · {targetLabel}
        </span>
      </div>
    </>
  )
}

/** Last ~6 calendar months of a daily/monthly snapshot series — the §3b
 * row-3 spec is a "6-month sparkline", not all-history. Date strings are
 * ISO (`YYYY-MM-DD`), so a lexicographic cutoff comparison is exact. */
function lastSixMonths(series: Goal['series']): Goal['series'] {
  if (series.length === 0) return series
  const last = new Date(`${series[series.length - 1].date}T00:00:00`)
  last.setMonth(last.getMonth() - 6)
  const cutoff = last.toISOString().slice(0, 10)
  return series.filter((p) => p.date >= cutoff)
}

/** T212 rebuild bubble's collapsed glance (docs/DESIGN.md §3b row 3):
 * current balance + 6-month sparkline (window stated — §2c.6) +
 * change-since-baseline line. */
export function RebuildGlance({ goal }: { goal: Goal }) {
  const changeSinceBaseline = goal.current_minor - goal.baseline_minor
  const series = lastSixMonths(goal.series)
  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>{formatMinorWhole(goal.current_minor)}</span>
      <div className="flex w-full items-center gap-2">
        <Sparkline series={series} width={96} height={20} className="min-w-0 flex-1" />
        <span className="shrink-0 font-mono text-[10px] text-ink-soft">6 mo</span>
      </div>
      <span className={`font-mono text-[11px] ${MONEY_CLASS} ${changeSinceBaseline >= 0 ? 'text-gain' : 'text-ink'}`}>
        {formatMinorSigned(changeSinceBaseline)} since baseline
      </span>
    </>
  )
}
