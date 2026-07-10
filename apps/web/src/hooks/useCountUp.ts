import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'

/** Count-up for the safe-to-spend hero figure — the one number Kakeibo
 * animates (docs/DESIGN.md §1: "motion is scarce by design — count-up on
 * the safe-to-spend number... and that's nearly it"). Runs once per target
 * for at most `durationMs` (§6: "count-ups run ≤600ms and land exactly"),
 * eases out, and always finishes on the exact integer-pence target — the
 * number is never left looking bigger or smaller than it is. Reduced
 * motion: no animation at all, the target renders immediately. The rAF loop
 * self-cancels on landing, so charts stay "static SVG, no rAF loops at
 * rest" (docs/phases/PHASE-7-dashboard.md item 6). */
export function useCountUpMinor(targetMinor: number, durationMs = 600): number {
  const reduced = useReducedMotion()
  const [value, setValue] = useState(reduced ? targetMinor : 0)
  const frame = useRef<number | null>(null)

  useEffect(() => {
    if (reduced) {
      setValue(targetMinor)
      return
    }
    const start = performance.now()
    const from = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs)
      const eased = 1 - (1 - t) ** 3
      setValue(t >= 1 ? targetMinor : Math.round(from + (targetMinor - from) * eased))
      if (t < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
    }
  }, [targetMinor, durationMs, reduced])

  return value
}
