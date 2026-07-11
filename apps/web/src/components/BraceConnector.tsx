import { motion, useMotionValue, useSpring, useTransform } from 'motion/react'
import { useEffect, useId } from 'react'

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
 * bubble"). Ported from Mishka Hub's liquid-connector concept
 * (`MovieCard.tsx`'s `expanded` halo: `border-liquid` + a
 * `from-liquid ... to-transparent` gradient), adapted for Kakeibo's plainer
 * rounded-square bubbles ("a desk, not a poster wall" — docs/DESIGN.md
 * intro): the brace stroke itself carries `var(--color-liquid)`, plus a
 * soft liquid-tinted fill pooling under the curve — a filled glass surface
 * rather than a bare stroke, but far subtler than Mishka's full poster
 * halo. The `--color-liquid` token is the shared canonical one
 * (theme.css — "Mishka's connector surface / Michi's trail").
 *
 * `overflow: visible` is explicit on the <svg> — the household's paid-for
 * gotcha (Mishka Hub App.tsx, docs/phases/PHASE-1-scaffold.md item 4):
 * a parent's rounded/clip styling can silently truncate a connector that
 * needs to render right at its box edge. Reduced motion is handled
 * globally by wrapping the app in `<MotionConfig reducedMotion="user">`
 * (App.tsx) rather than branching here. */
export function BraceConnector({ width, peakX }: { width: number; peakX: number }) {
  const gradientId = useId()
  const rawX = useMotionValue(peakX)
  useEffect(() => {
    rawX.set(peakX)
  }, [peakX, rawX])
  const springX = useSpring(rawX, { stiffness: 260, damping: 28 })
  const d = useTransform(springX, (x) => bracePath(width, x))
  // Same curve, closed back along the baseline (the path already starts and
  // ends on y=HEIGHT, so `Z` closes it with a straight bottom edge) — used
  // only as a fill region, the stroked `d` above still draws the crisp line.
  const fillD = useTransform(d, (path) => `${path} Z`)

  return (
    <svg
      width={width}
      height={HEIGHT}
      viewBox={`0 0 ${width} ${HEIGHT}`}
      style={{ overflow: 'visible' }}
      aria-hidden
      className="block"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1={HEIGHT} x2="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="25%" stopColor="var(--color-liquid)" stopOpacity={0.55} />
          <stop offset="70%" stopColor="var(--color-liquid)" stopOpacity={0} />
        </linearGradient>
      </defs>
      <motion.path d={fillD} fill={`url(#${gradientId})`} stroke="none" />
      <motion.path d={d} fill="none" stroke="var(--color-liquid)" strokeOpacity={0.9} strokeWidth={1.5} />
    </svg>
  )
}
