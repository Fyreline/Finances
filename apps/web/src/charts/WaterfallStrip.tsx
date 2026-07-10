import { useId } from 'react'
import { MONEY_CLASS, formatMinor } from '../money'
import { useBarFill } from './useBarFill'

// docs/DESIGN.md §4a / §5 — the whole month's income as one horizontal
// stacked bar: committed, goals, tax set-aside (hatched), buffer,
// spent-so-far, remaining. Per the §5 primitive spec this is real SVG —
// stacked `<rect>`s with an SVG `<pattern>` for the hatched segment and a
// 200ms width transition on load (none under reduced motion, via
// `useBarFill`). Segments sum pence-exact to income (the safe-to-spend
// waterfall made visible — API.md §6a). Colour is never the only signal:
// every segment carries a legend chip with its label + amount
// (docs/DESIGN.md §2c.2), and paper-coloured seams keep adjacent segments
// separable without relying on hue at all.
//
// Colours are semantic tokens only — Tailwind `text-*` classes driving
// `currentColor` for the rects (the codebase's SVG idiom) and `bg-*`
// utilities for the legend chips, all written out literally for the
// build-time scanner (same precedent as categoryColor.ts).

export interface WaterfallSegment {
  key: string
  label: string
  minor: number // positive magnitude (remaining may be negative — legend only)
  /** `bg-*` utility for the legend chip. */
  className: string
  /** `text-*` utility for the SVG rect (drawn via currentColor). */
  svgClassName: string
  fillOpacity?: number
  hatched?: boolean
}

/** Build the six §4a segments from a safe-to-spend payload. `remaining` is
 * shown in `gain`, or `over` (crimson) when negative — the one honest
 * threshold state (docs/DESIGN.md §6). A negative remaining is rendered as a
 * zero-width bar segment (it has no positive area) but always appears in the
 * legend with its real, negative figure. */
export function safeToSpendSegments(s: {
  committed_minor: number
  goal_set_aside_minor: number
  tax_set_aside_minor: number
  buffer_minor: number
  spent_so_far_minor: number
  remaining_minor: number | null
}): WaterfallSegment[] {
  const remaining = s.remaining_minor ?? 0
  return [
    { key: 'committed', label: 'Committed', minor: s.committed_minor, className: 'bg-viz-5', svgClassName: 'text-viz-5' },
    { key: 'goals', label: 'Goals', minor: s.goal_set_aside_minor, className: 'bg-setaside', svgClassName: 'text-setaside' },
    {
      key: 'tax',
      label: 'Tax set-aside',
      minor: s.tax_set_aside_minor,
      className: 'bg-setaside/60',
      svgClassName: 'text-setaside',
      fillOpacity: 0.6,
      hatched: true,
    },
    { key: 'buffer', label: 'Buffer', minor: s.buffer_minor, className: 'bg-oat', svgClassName: 'text-oat' },
    { key: 'spent', label: 'Spent so far', minor: s.spent_so_far_minor, className: 'bg-ink/30', svgClassName: 'text-ink', fillOpacity: 0.3 },
    {
      key: 'remaining',
      label: 'Remaining',
      minor: remaining,
      className: remaining < 0 ? 'bg-over' : 'bg-gain',
      svgClassName: remaining < 0 ? 'text-over' : 'text-gain',
    },
  ]
}

/** The §4a hatch — diagonal paper-coloured lines over the segment's own
 * colour, so the "committed but not yet moved" tax money reads differently
 * from the solid goals segment even in a greyscale/deuteranopia rendering. */
function HatchPattern({ id }: { id: string }) {
  return (
    <pattern id={id} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="5" height="5" fill="currentColor" />
      <line x1="0" y1="0" x2="0" y2="5" stroke="var(--color-paper)" strokeWidth="1.6" />
    </pattern>
  )
}

function LegendSwatch({ seg, hatchId }: { seg: WaterfallSegment; hatchId: string }) {
  if (seg.hatched) {
    return (
      <svg width="10" height="10" className={`rounded-sm border border-line-strong ${seg.svgClassName}`} aria-hidden>
        <rect width="10" height="10" fill={`url(#${hatchId})`} opacity={seg.fillOpacity ?? 1} />
      </svg>
    )
  }
  return <span className={`inline-block h-2.5 w-2.5 rounded-sm border border-line-strong ${seg.className}`} aria-hidden />
}

export function WaterfallStrip({
  segments,
  totalMinor,
  height = 12,
  showLegend = true,
}: {
  segments: WaterfallSegment[]
  totalMinor: number
  height?: number
  showLegend?: boolean
}) {
  const hatchId = useId()
  const denom = totalMinor > 0 ? totalMinor : 1
  // 200ms width transition on load (docs/DESIGN.md §5) — scaleX the whole
  // stack from the left; useBarFill holds it until the panel settles and
  // skips it entirely under reduced motion.
  const scale = useBarFill(100) / 100

  let acc = 0
  const placed = segments
    .map((seg) => {
      const pct = Math.max(0, (seg.minor / denom) * 100)
      const x = acc
      acc += pct
      return { seg, x, pct }
    })
    .filter((p) => p.pct > 0)

  return (
    <div className="w-full space-y-2">
      <svg
        width="100%"
        height={height}
        role="img"
        aria-label="Income allocation waterfall"
        className="block overflow-hidden rounded-sm border border-line-strong"
      >
        <g
          style={{ transform: `scaleX(${scale})`, transformOrigin: 'left' }}
          className="motion-safe:transition-transform motion-safe:duration-200"
        >
          {placed.map(({ seg, x, pct }) => (
            <g key={seg.key} className={seg.svgClassName}>
              <rect
                x={`${x}%`}
                y="0"
                width={`${pct}%`}
                height="100%"
                fill={seg.hatched ? `url(#${hatchId})` : 'currentColor'}
                fillOpacity={seg.fillOpacity ?? 1}
                stroke="var(--color-paper)"
                strokeWidth="1"
              >
                <title>{`${seg.label} · ${formatMinor(seg.minor)}`}</title>
              </rect>
              {seg.hatched && <HatchPattern id={hatchId} />}
            </g>
          ))}
        </g>
      </svg>
      {showLegend && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {segments.map((seg) => (
            <li key={seg.key} className="flex items-center gap-1.5">
              <span className={seg.svgClassName}>
                <LegendSwatch seg={seg} hatchId={hatchId} />
              </span>
              <span className="font-mono text-[11px] text-ink-soft">{seg.label}</span>
              <span className={`text-[11px] ${MONEY_CLASS} text-ink-mid`}>{formatMinor(seg.minor)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
