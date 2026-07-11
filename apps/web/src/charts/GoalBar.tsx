import type { GoalStatus } from '../api'
import { formatMinor, formatMinorWhole, formatMinorWholeCeil, MONEY_CLASS } from '../money'
import { shapeGoalBar } from './shape'
import { useBarFill } from './useBarFill'
import { GOAL_VERDICT_LABEL, GOAL_VERDICT_STYLE } from './verdict'

export interface GoalBarProps {
  currentMinor: number
  targetMinor: number
  targetDate: string
  projectedAtTargetMinor: number | null
  requiredPerMonthMinor: number | null
  trendPerMonthMinor: number | null
  status: GoalStatus
  catchUpPerMonthMinor: number | null
}

/** docs/DESIGN.md §4c — progress bar + target tick + projection marker +
 * verdict pill + the catch-up sentence when behind. */
export function GoalBar({
  currentMinor,
  targetMinor,
  targetDate,
  projectedAtTargetMinor,
  requiredPerMonthMinor,
  trendPerMonthMinor,
  status,
  catchUpPerMonthMinor,
}: GoalBarProps) {
  const { fillPct, projectedPct } = shapeGoalBar(currentMinor, targetMinor, projectedAtTargetMinor)
  const fillWidth = useBarFill(fillPct * 100)
  const targetDateLabel = new Date(`${targetDate}T00:00:00`).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Progress</span>
        <span className={`rounded-full px-2 py-0.5 font-mono text-[11px] uppercase tracking-[0.06em] ${GOAL_VERDICT_STYLE[status]}`}>
          {GOAL_VERDICT_LABEL[status]}
        </span>
      </div>

      <div className="relative h-3 rounded-full bg-paper-deep">
        {/* Fill draws in once the panel settles (docs/DESIGN.md §1
            "progress-bar fill on load", §3c "charts mount after the panel
            settles"); useBarFill skips the animation under reduced motion. */}
        <div
          className="h-3 rounded-full bg-setaside motion-safe:transition-[width] motion-safe:duration-500"
          style={{ width: `${fillWidth.toFixed(1)}%` }}
        />
        {/* target tick */}
        <div className="absolute inset-y-0 right-0 w-0.5 bg-ink" aria-hidden />
        {projectedPct !== null && (
          <div
            className="absolute top-1/2 h-2.5 w-2.5 -translate-y-1/2 rounded-full border-2 border-paper"
            style={{ left: `calc(${(projectedPct * 100).toFixed(1)}% - 5px)` }}
          >
            <span
              className={`block h-full w-full rounded-full ${
                projectedAtTargetMinor !== null && projectedAtTargetMinor >= targetMinor ? 'bg-gain' : 'bg-kraft'
              }`}
            />
          </div>
        )}
      </div>

      <div className={`flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] ${MONEY_CLASS}`}>
        <span>
          {formatMinor(currentMinor)} of {formatMinor(targetMinor)}
        </span>
        <span className="text-ink-soft">·</span>
        <span className="text-ink-soft">target {targetDateLabel}</span>
        {requiredPerMonthMinor !== null && (
          <>
            <span className="text-ink-soft">·</span>
            {/* Ceil, never round-half, at this final pence-to-pound step
                too — a required-per-month figure must never flatter the
                user (docs/ARCHITECTURE.md §6). */}
            <span>{formatMinorWholeCeil(requiredPerMonthMinor)}/mo needed</span>
          </>
        )}
        {trendPerMonthMinor !== null && (
          <>
            <span className="text-ink-soft">·</span>
            <span className="text-ink-soft">trend {formatMinorWhole(trendPerMonthMinor)}/mo</span>
          </>
        )}
      </div>

      {status === 'behind' && catchUpPerMonthMinor !== null && (
        <p className="font-serif text-sm text-ink-mid">
          Behind — <span className={MONEY_CLASS}>{formatMinorWholeCeil(catchUpPerMonthMinor)}</span>/month from now
          reaches it.
        </p>
      )}
    </div>
  )
}
