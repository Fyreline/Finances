import { useCallback, useEffect, useState } from 'react'
import { api, type SafeToSpend } from '../api'

export interface SafeToSpendState {
  data: SafeToSpend | null
  loading: boolean
  error: string | null
  reload: () => void
}

/** Fetches `GET /api/summary/safe-to-spend` (docs/API.md §6a). Shared by the
 * hero bubble's glance and its detail panel; `reload()` lets the detail's
 * config form refresh the number after a save. */
export function useSafeToSpend(): SafeToSpendState {
  const [data, setData] = useState<SafeToSpend | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api
      .safeToSpend()
      .then((res) => !cancelled && setData(res))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : "Couldn't load"))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, loading, error, reload }
}
