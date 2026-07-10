import { useRef, useState } from 'react'
import { formatMinor, formatMinorWhole } from '../money'
import { shapeTargetLineY, shapeTrendLine, type SeriesPoint, type TrendPoint } from './shape'
import { useBarFill } from './useBarFill'

export interface TrendLineProps {
  series: SeriesPoint[]
  width?: number
  height?: number
  targetMinor?: number | null
  /** Renders a labelled marker at this point in the series (e.g. the
   * baseline snapshot — docs/DESIGN.md §4c "baseline annotation"). */
  baseline?: { date: string; valueMinor: number } | null
  colorClassName?: string
  className?: string
}

/** `2026-09-01` -> `1 Sep` — the §5 tooltip's date shape. */
function tooltipDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** docs/DESIGN.md §5: "x time, y £; area fill token at 12% opacity under a
 * 2px line; dotted target line + tick; hover (pointer) / tap (touch) →
 * vertical rule + mono tooltip `1 Sep · £4,120`". The line draws in over
 * ≤600ms once its container settles (§3c, via `useBarFill`/`SettleContext`);
 * under reduced motion it renders complete immediately. */
export function TrendLine({
  series,
  width = 320,
  height = 120,
  targetMinor = null,
  baseline = null,
  colorClassName = 'text-viz-5',
  className = '',
}: TrendLineProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<TrendPoint | null>(null)
  const drawn = useBarFill(1) === 1
  const shape = shapeTrendLine(series, width, height)

  if (shape.points.length === 0) {
    return (
      <p className="font-serif text-sm text-ink-mid">Not enough history yet for a trend chart.</p>
    )
  }

  const targetY =
    targetMinor !== null ? shapeTargetLineY(targetMinor, shape.minValueMinor, shape.maxValueMinor, height) : null

  const baselinePoint = baseline
    ? shape.points.find((p) => p.date === baseline.date) ??
      shape.points.reduce((closest, p) => (p.date <= baseline.date ? p : closest), shape.points[0])
    : null

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    // The svg renders at 100% width — map the pointer back into viewBox x.
    const x = ((e.clientX - rect.left) / rect.width) * width
    const nearest = shape.points.reduce((a, b) => (Math.abs(b.x - x) < Math.abs(a.x - x) ? b : a))
    setHover(nearest)
  }

  // Keep the tooltip text inside the viewBox whichever end it hovers.
  const hoverAnchor = hover === null ? 'start' : hover.x > width * 0.66 ? 'end' : hover.x < width * 0.33 ? 'start' : 'middle'

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      className={className}
      role="img"
      aria-label="balance trend"
      onPointerMove={onPointerMove}
      onPointerLeave={() => setHover(null)}
    >
      <path
        d={shape.areaPath}
        className={`${colorClassName} motion-safe:transition-opacity motion-safe:duration-500`}
        fill="currentColor"
        fillOpacity={drawn ? 0.12 : 0}
        stroke="none"
      />
      <path
        d={shape.path}
        className={`${colorClassName} motion-safe:transition-[stroke-dashoffset] motion-safe:duration-500 motion-safe:ease-out`}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={drawn ? 0 : 1}
      />
      {targetY !== null && (
        <line
          x1={0}
          x2={width}
          y1={targetY}
          y2={targetY}
          className="text-line-strong"
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
      )}
      {baselinePoint && (
        <>
          <circle cx={baselinePoint.x} cy={baselinePoint.y} r={3} className="text-ink-soft" fill="currentColor" />
          <text
            x={baselinePoint.x}
            y={Math.max(baselinePoint.y - 8, 10)}
            className="fill-ink-soft font-mono"
            fontSize={10}
            textAnchor="start"
          >
            baseline {formatMinorWhole(baseline!.valueMinor)}
          </text>
        </>
      )}
      {hover && (
        <g aria-hidden>
          <line x1={hover.x} x2={hover.x} y1={0} y2={height} className="text-line-strong" stroke="currentColor" strokeWidth={1} />
          <circle cx={hover.x} cy={hover.y} r={3} className={colorClassName} fill="currentColor" />
          <text
            x={Math.min(Math.max(hover.x, 4), width - 4)}
            y={12}
            className="fill-ink font-mono"
            fontSize={10}
            textAnchor={hoverAnchor}
          >
            {tooltipDate(hover.date)} · {formatMinor(hover.valueMinor)}
          </text>
        </g>
      )}
    </svg>
  )
}
