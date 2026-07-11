import { motion, useMotionValue, useSpring, useTransform } from 'motion/react'
import { useEffect } from 'react'

const NECK_H = 28
const WAIST_BASE = 18
const FLARE = 24

/** A filled hourglass/pinch shape between the active bubble's bottom edge
 * and the detail panel's top edge — ported from Mishka Hub's `LiquidConnector`
 * (`MishkaHub/apps/web/src/App.tsx`, `liquidPath()`), simplified for Kakeibo's
 * flatter "a desk, not a poster wall" language (docs/DESIGN.md intro): no
 * halo-glow behind the bubble, no separate/merge two-menisci sub-phase for
 * the open beat, no snap-detach choreography on switch — the household's own
 * simplification (2026-07-12 follow-up: "when switching detail boxes...
 * stay open... instead of a smooth animation just close it straight away").
 * What carries over faithfully is the actual SHAPE: a filled path (not a
 * stroked line — the first attempt at this, Phase 10, only changed the
 * stroke colour on the old curly-brace outline and missed the real
 * mechanism entirely) whose waist genuinely pinches between two wider ends,
 * tangent to the flat edges it leaves and lands on, the same way Mishka's
 * does. */
function hourglassPath(rowW: number, centerX: number, bubbleW: number, grow: number): string {
  const g = Math.max(0, Math.min(1.08, grow))
  const topHW = bubbleW / 2
  const joinY = 0
  const botY = NECK_H
  const midY = NECK_H / 2
  const leftFlareHW = Math.max(Math.min(topHW + FLARE, centerX), topHW)
  const rightFlareHW = Math.max(Math.min(topHW + FLARE, rowW - centerX), topHW)
  const leftT = centerX - topHW
  const rightT = centerX + topHW
  const leftB = centerX - leftFlareHW
  const rightB = centerX + rightFlareHW
  const waist = WAIST_BASE * g
  const w = Math.max(0.5, Math.min(waist, leftFlareHW - 3, rightFlareHW - 3, topHW - 2))
  return [
    `M${leftT},${joinY}`,
    `C${leftT + (centerX - w - leftT) * 0.6},${joinY} ${centerX - w},${midY * 0.55} ${centerX - w},${midY}`,
    `C${centerX - w},${midY + (botY - midY) * 0.45} ${leftB + (centerX - w - leftB) * 0.62},${botY} ${leftB},${botY}`,
    `L${rightB},${botY}`,
    `C${rightB - (rightB - (centerX + w)) * 0.62},${botY} ${centerX + w},${midY + (botY - midY) * 0.45} ${centerX + w},${midY}`,
    `C${centerX + w},${midY * 0.55} ${rightT - (rightT - (centerX + w)) * 0.6},${joinY} ${rightT},${joinY}`,
    'Z',
  ].join(' ')
}

/** Connects the active bubble to its detail panel below it. `width`/`peakX`/
 * `bubbleW` all track their target via spring (not a jump) — this is what
 * makes switching between two open bubbles read as the neck *sliding* to
 * the new one rather than closing and reopening (docs/DESIGN.md §3c;
 * 2026-07-12 fix — the actual close/reopen bug was the panel remounting on
 * every switch in `HomePage.tsx`, not this component, but the connector
 * still needs to glide rather than jump for the fix to read as one motion,
 * not two). `overflow: visible` stays explicit (household gotcha, Mishka
 * Hub App.tsx / docs/phases/PHASE-1-scaffold.md item 4). */
export function BraceConnector({ width, peakX, bubbleW }: { width: number; peakX: number; bubbleW: number }) {
  const rawX = useMotionValue(peakX)
  const rawW = useMotionValue(width)
  const rawBubbleW = useMotionValue(bubbleW)
  useEffect(() => {
    rawX.set(peakX)
    rawW.set(width)
    rawBubbleW.set(bubbleW)
  }, [peakX, width, bubbleW, rawX, rawW, rawBubbleW])
  const spring = { stiffness: 320, damping: 30 }
  const springX = useSpring(rawX, spring)
  const springW = useSpring(rawW, spring)
  const springBubbleW = useSpring(rawBubbleW, spring)

  const d = useTransform([springW, springX, springBubbleW] as const, ([w, x, bw]: number[]) =>
    hourglassPath(w, x, bw, 1),
  )

  return (
    <svg
      width={width}
      height={NECK_H}
      viewBox={`0 0 ${width} ${NECK_H}`}
      style={{ overflow: 'visible' }}
      aria-hidden
      className="block text-liquid"
    >
      <motion.path d={d} fill="currentColor" />
    </svg>
  )
}
