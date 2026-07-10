// Pure data-shaping functions for the chart primitives (docs/DESIGN.md §5:
// "All primitives take pre-shaped {label, value_minor, token} arrays —
// shaping happens in testable functions, rendering is dumb"). No DOM, no
// React here — every function is plain arithmetic over plain data, which is
// what makes it vitest-coverable without mounting anything.

export interface SeriesPoint {
  date: string
  value_minor: number
}

function extent(values: number[]): [number, number] {
  if (values.length === 0) return [0, 0]
  return [Math.min(...values), Math.max(...values)]
}

// --------------------------------------------------------------- Sparkline
export interface SparklineShape {
  /** SVG `<polyline points="...">` attribute value, `''` when empty. */
  points: string
  firstValueMinor: number | null
  lastValueMinor: number | null
}

/** Maps a value series onto an SVG viewport (y flipped — SVG y grows down).
 * Docs/DESIGN.md §5 Sparkline spec: "nulls break the line, never
 * interpolate" — Kakeibo's snapshot series never carries an explicit null
 * today, so there's nothing to break on, but the shaping stays pure and
 * span-per-point so a future null-aware caller could split `points` on its
 * own without this function needing to change. */
export function shapeSparkline(series: SeriesPoint[], width = 96, height = 24): SparklineShape {
  if (series.length === 0) return { points: '', firstValueMinor: null, lastValueMinor: null }
  const values = series.map((p) => p.value_minor)
  const [min, max] = extent(values)
  const range = max - min || 1
  const stepX = series.length > 1 ? width / (series.length - 1) : 0
  const points = series
    .map((p, i) => {
      const x = i * stepX
      const y = height - ((p.value_minor - min) / range) * height
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
  return { points, firstValueMinor: values[0], lastValueMinor: values[values.length - 1] }
}

// --------------------------------------------------------------- TrendLine
export interface TrendPoint {
  x: number
  y: number
  date: string
  valueMinor: number
}

export interface TrendLineShape {
  /** SVG `<path d="...">` for the line itself. */
  path: string
  /** SVG `<path d="...">` for the area fill beneath the line (closed to the
   * viewport's bottom edge — docs/DESIGN.md §5 "area fill token at 12%
   * opacity under a 2px line"). */
  areaPath: string
  points: TrendPoint[]
  minValueMinor: number
  maxValueMinor: number
}

/** Trend lines may zoom the y-domain to the data's own min/max — not forced
 * to start at zero like a bar chart (docs/DESIGN.md §2c.5: "bars start at
 * zero, always... Trend lines may zoom the y-domain but then show a dotted
 * zero/target reference" — the reference line itself is the renderer's job,
 * not this shaping function's). */
export function shapeTrendLine(series: SeriesPoint[], width = 320, height = 120): TrendLineShape {
  if (series.length === 0) {
    return { path: '', areaPath: '', points: [], minValueMinor: 0, maxValueMinor: 0 }
  }
  const values = series.map((p) => p.value_minor)
  const [min, max] = extent(values)
  const range = max - min || 1
  const stepX = series.length > 1 ? width / (series.length - 1) : 0

  const points: TrendPoint[] = series.map((p, i) => ({
    x: i * stepX,
    y: height - ((p.value_minor - min) / range) * height,
    date: p.date,
    valueMinor: p.value_minor,
  }))

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')
  const last = points[points.length - 1]
  const first = points[0]
  const areaPath = `${path} L${last.x.toFixed(2)},${height} L${first.x.toFixed(2)},${height} Z`

  return { path, areaPath, points, minValueMinor: min, maxValueMinor: max }
}

/** Maps a target value onto the same y-domain a TrendLine was shaped with,
 * for the dotted target reference line (docs/DESIGN.md §2c.5) — `null` if
 * the target falls outside a domain so degenerate (a flat single-point
 * series) that a ratio is meaningless. */
export function shapeTargetLineY(targetMinor: number, minValueMinor: number, maxValueMinor: number, height = 120): number | null {
  const range = maxValueMinor - minValueMinor
  if (range === 0) return null
  return height - ((targetMinor - minValueMinor) / range) * height
}

// ----------------------------------------------------------------- GoalBar
export interface GoalBarShape {
  /** 0..1 fraction of `targetMinor` the current balance fills, clamped. */
  fillPct: number
  /** 0..1 fraction of `targetMinor` the projected-at-target balance sits
   * at, clamped so a wildly over/under projection still renders on the
   * bar; `null` when there's no projection yet (docs/DATA_MODEL.md §4a
   * `no_trend`). */
  projectedPct: number | null
}

/** `null`/`<= 0` target -> zero fill: an open-ended goal (t212_rebuild) has
 * "no target bar" at all (docs/DESIGN.md §4c) — callers branch on
 * `targetMinor === null` before rendering a bar in the first place; this
 * function just refuses to divide by a non-positive target either way. */
export function shapeGoalBar(currentMinor: number, targetMinor: number | null, projectedMinor: number | null): GoalBarShape {
  if (!targetMinor || targetMinor <= 0) return { fillPct: 0, projectedPct: null }
  const clamp = (n: number) => Math.max(0, Math.min(1, n))
  return {
    fillPct: clamp(currentMinor / targetMinor),
    projectedPct: projectedMinor === null ? null : clamp(projectedMinor / targetMinor),
  }
}
