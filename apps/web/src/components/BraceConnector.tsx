import { motion, useMotionValue, useSpring, useTransform } from 'motion/react'
import { useEffect } from 'react'

const HEIGHT = 20

function bracePath(width: number, peakX: number): string {
  const clampedPeak = Math.min(Math.max(peakX, 28), Math.max(width - 28, 28))
  const spread = Math.min(70, width / 3)
  return `M0,${HEIGHT} C${clampedPeak - spread},${HEIGHT} ${clampedPeak - 16},1 ${clampedPeak},1 C${
    clampedPeak + 16
  },1 ${clampedPeak + spread},${HEIGHT} ${width},${HEIGHT}`
}

/** Connects an expanded bubble to its detail panel below it — a curly-
 * brace-shaped outline whose peak tracks the active bubble's horizontal
 * centre (docs/DESIGN.md §3c: "peak slides on useSpring to the active
 * bubble"). Simplified port of Mishka Hub's liquid-connector concept,
 * adapted for Kakeibo's plainer rounded-square bubbles ("a desk, not a
 * poster wall" — docs/DESIGN.md intro): a single stroked brace rather than
 * a filled liquid-glass shape.
 *
 * `overflow: visible` is explicit on the <svg> — the household's paid-for
 * gotcha (Mishka Hub App.tsx, docs/phases/PHASE-1-scaffold.md item 4):
 * a parent's rounded/clip styling can silently truncate a connector that
 * needs to render right at its box edge. Reduced motion is handled
 * globally by wrapping the app in `<MotionConfig reducedMotion="user">`
 * (App.tsx) rather than branching here. */
export function BraceConnector({ width, peakX }: { width: number; peakX: number }) {
  const rawX = useMotionValue(peakX)
  useEffect(() => {
    rawX.set(peakX)
  }, [peakX, rawX])
  const springX = useSpring(rawX, { stiffness: 260, damping: 28 })
  const d = useTransform(springX, (x) => bracePath(width, x))

  return (
    <svg
      width={width}
      height={HEIGHT}
      viewBox={`0 0 ${width} ${HEIGHT}`}
      style={{ overflow: 'visible' }}
      aria-hidden
      className="block"
    >
      <motion.path d={d} fill="none" stroke="var(--color-clay)" strokeOpacity={0.6} strokeWidth={1.5} />
    </svg>
  )
}
