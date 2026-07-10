import { GoalBar } from '../../charts/GoalBar'
import { useGoals } from '../../hooks/useGoals'
import { PlaceholderDetail } from './PlaceholderDetail'

/** House deposit goal detail (docs/DESIGN.md §4c, docs/DATA_MODEL.md §4a).
 * Real target/deadline/baseline are loaded from local runtime config at
 * seed time (docs/PRIVATE.md's redaction scheme, docs/phases/
 * PHASE-3-t212-goals.md item 4) — this component only ever renders whatever
 * `GET /api/goals` returns, never a hardcoded figure. */
export function DepositDetail() {
  const { goalsByKey, loading, error } = useGoals()
  const goal = goalsByKey.house_deposit

  if (loading) {
    return <p className="font-serif text-sm text-ink-mid">Loading…</p>
  }
  if (error) {
    return <p className="font-serif text-sm text-ink-mid">Couldn't load the deposit goal ({error}).</p>
  }
  if (!goal || goal.target_minor === null || goal.target_date === null) {
    return (
      <PlaceholderDetail
        title="House deposit"
        body="Set a target and deadline for this goal in local config to unlock the progress bar and monthly-required figure (docs/PRIVATE.md, docs/SECRETS.md)."
        phase="Wired up in Phase 3 (docs/DATA_MODEL.md §4)"
      />
    )
  }

  return (
    <div className="max-w-2xl space-y-4">
      <h3 className="font-display text-lg font-medium text-ink">House deposit</h3>
      <GoalBar
        currentMinor={goal.current_minor}
        targetMinor={goal.target_minor}
        targetDate={goal.target_date}
        projectedAtTargetMinor={goal.projected_at_target_minor}
        requiredPerMonthMinor={goal.required_per_month_minor}
        trendPerMonthMinor={goal.trend_per_month_minor}
        status={goal.status}
        catchUpPerMonthMinor={goal.catch_up_per_month_minor}
      />
    </div>
  )
}
