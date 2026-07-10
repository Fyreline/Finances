import { useEffect, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { useSettled } from './settle'

/** Drives a bar's fill from 0 to its real value once its container has
 * settled — the "progress-bar fill on load" draw-in (docs/DESIGN.md §1),
 * held until the expand transition finishes when the bar lives inside a
 * detail panel (§3c via `SettleContext`). The caller pairs the returned
 * width with `motion-safe:transition-[width]`; under reduced motion this
 * returns the target immediately, so there is nothing to animate and the
 * bar renders at rest (§3c "reduced motion: ... no bar-fill"). */
export function useBarFill(targetPct: number): number {
  const reduced = useReducedMotion()
  const settled = useSettled()
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!settled) return
    // One frame at 0 so the width change actually transitions.
    const frame = requestAnimationFrame(() => setArmed(true))
    return () => cancelAnimationFrame(frame)
  }, [settled])

  if (reduced) return targetPct
  return armed && settled ? targetPct : 0
}
