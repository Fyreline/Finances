import { shapeSparkline, type SeriesPoint } from './shape'

export interface SparklineProps {
  series: SeriesPoint[]
  width?: number
  height?: number
  /** A Tailwind `text-*` class resolving to a semantic/viz token — line and
   * dot both draw via `currentColor` off it, the standard SVG-icon idiom.
   * A raw hex here is a review-blocker (docs/DESIGN.md §1). */
  colorClassName?: string
  className?: string
}

/** docs/DESIGN.md §5: "48-120x16-24px, 1.5px path viz-5 (or semantic token
 * by series), no axes, dot on last point, first/last labels optional." */
export function Sparkline({
  series,
  width = 96,
  height = 24,
  colorClassName = 'text-viz-5',
  className = '',
}: SparklineProps) {
  const { points, lastValueMinor } = shapeSparkline(series, width, height)

  if (!points) {
    return (
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className={className} aria-hidden />
    )
  }

  const lastPoint = points.split(' ').at(-1)
  const [lastX, lastY] = lastPoint ? lastPoint.split(',').map(Number) : [0, 0]

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={`${colorClassName} ${className}`}
      role="img"
      aria-label={lastValueMinor !== null ? `trend, latest value ${lastValueMinor} pence` : 'trend'}
    >
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} />
      <circle cx={lastX} cy={lastY} r={2} fill="currentColor" stroke="none" />
    </svg>
  )
}
