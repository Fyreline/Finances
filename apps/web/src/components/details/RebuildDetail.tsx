import { TrendLine } from '../../charts/TrendLine'
import { useGoals } from '../../hooks/useGoals'
import { formatMinor, formatMinorWhole, MONEY_CLASS } from '../../money'
import { PlaceholderDetail } from './PlaceholderDetail'

/** T212 rebuild goal detail (docs/DESIGN.md §4c "T212 rebuild variant" —
 * open-ended, no target bar; a balance-growth trend chart with a baseline
 * annotation instead). The series honestly conflates contributions with
 * market movement, so the label says "balance growth", never
 * "contributions" (docs/DATA_MODEL.md §4). */
export function RebuildDetail() {
  const { goalsByKey, loading, error } = useGoals()
  const goal = goalsByKey.t212_rebuild

  if (loading) {
    return <p className="font-serif text-sm text-ink-mid">Loading…</p>
  }
  if (error) {
    return <p className="font-serif text-sm text-ink-mid">Couldn't load the rebuild goal ({error}).</p>
  }
  if (!goal) {
    return (
      <PlaceholderDetail
        title="T212 rebuild"
        body="Set a baseline for this goal in local config to unlock the balance-growth trend chart (docs/PRIVATE.md, docs/SECRETS.md)."
        phase="Wired up in Phase 3 (docs/DATA_MODEL.md §4)"
      />
    )
  }

  // The chart states its own window (docs/DESIGN.md §2c.6) — everything
  // since the first snapshot (or the configured baseline, before any exist).
  const windowStart = goal.series[0]?.date ?? goal.baseline_date
  const windowLabel = new Date(`${windowStart}T00:00:00`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

  return (
    <div className="max-w-2xl space-y-4">
      <h3 className="font-display text-lg font-medium text-ink">Trading 212 rebuild</h3>
      <div className={`text-2xl ${MONEY_CLASS} text-ink`}>{formatMinor(goal.current_minor)}</div>
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
        balance growth since {windowLabel} — includes market movement, not contributions alone
      </p>
      <TrendLine
        series={goal.series}
        // Dotted reference at the baseline — a zoomed y-domain always shows
        // one (docs/DESIGN.md §2c.5), and for an open-ended rebuild the
        // baseline is the honest reference, there being no target.
        targetMinor={goal.baseline_minor}
        baseline={{ date: goal.baseline_date, valueMinor: goal.baseline_minor }}
      />
      {goal.trend_per_month_minor !== null && (
        <p className={`text-sm ${MONEY_CLASS} text-ink-mid`}>
          trend {formatMinorWhole(goal.trend_per_month_minor)}/month
        </p>
      )}
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
        baseline {formatMinor(goal.baseline_minor)} · {goal.baseline_date}
      </p>
    </div>
  )
}
