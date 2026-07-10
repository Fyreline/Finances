import { useEffect, useState } from 'react'
import { api, type Goal } from '../api'

export interface GoalsState {
  goalsByKey: Record<string, Goal>
  loading: boolean
  error: string | null
}

/** Fetches `GET /api/goals` once and indexes by `key` — shared by the
 * Deposit/Rebuild bubbles' collapsed glance content and their detail views
 * so both read the same live data (docs/phases/PHASE-3-t212-goals.md item
 * 5). No polling here; the sync-status pill (Phase 2) already tells the
 * user when fresher data might exist — a manual reload is enough for this
 * phase. */
export function useGoals(): GoalsState {
  const [goalsByKey, setGoalsByKey] = useState<Record<string, Goal>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .goals()
      .then((res) => {
        if (cancelled) return
        const byKey: Record<string, Goal> = {}
        for (const goal of res.goals) byKey[goal.key] = goal
        setGoalsByKey(byKey)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "Couldn't load goals")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { goalsByKey, loading, error }
}
