import { createContext, useContext } from 'react'

/** "Expansion animates height/opacity only (no layout thrash on the charts —
 * charts mount after the panel settles, then run their ≤600ms draw-in)"
 * (docs/DESIGN.md §3c). Detail panels/sheets provide `false` until their
 * open transition completes; chart primitives hold their draw-in until it
 * flips true. Defaults to `true` so charts rendered outside an expanding
 * container (collapsed bubble glances) draw on load as §1 specifies
 * ("progress-bar fill on load"). Reduced motion needs no branch here — the
 * providers flip to `true` immediately (MotionConfig makes their transition
 * instant) and the draw-ins themselves are `motion-safe:`/`useReducedMotion`
 * gated. */
export const SettleContext = createContext(true)

export function useSettled(): boolean {
  return useContext(SettleContext)
}
