import { describe, expect, it } from 'vitest'
import { shapeGoalBar, shapeSparkline, shapeTargetLineY, shapeTrendLine } from './shape'

describe('shapeSparkline', () => {
  it('returns empty shape for an empty series', () => {
    expect(shapeSparkline([])).toEqual({ points: '', firstValueMinor: null, lastValueMinor: null })
  })

  it('places a single point at x=0', () => {
    const shape = shapeSparkline([{ date: '2026-07-01', value_minor: 1000 }], 96, 24)
    // A single point has no range, so it falls back to a range of 1 and
    // (value - min) is always 0 -> y sits at the viewport's bottom edge.
    expect(shape.points).toBe('0.00,24.00')
    expect(shape.firstValueMinor).toBe(1000)
    expect(shape.lastValueMinor).toBe(1000)
  })

  it('spans the full width across the series and flips y (SVG y grows down)', () => {
    const shape = shapeSparkline(
      [
        { date: '2026-05-01', value_minor: 0 },
        { date: '2026-06-01', value_minor: 50 },
        { date: '2026-07-01', value_minor: 100 },
      ],
      100,
      20,
    )
    const points = shape.points.split(' ')
    expect(points).toHaveLength(3)
    expect(points[0]).toBe('0.00,20.00') // lowest value -> bottom of the viewport
    expect(points[2]).toBe('100.00,0.00') // highest value -> top of the viewport
  })

  it('reports first/last raw values regardless of scaling', () => {
    const shape = shapeSparkline([
      { date: '2026-05-01', value_minor: 30000 },
      { date: '2026-07-01', value_minor: 42000 },
    ])
    expect(shape.firstValueMinor).toBe(30000)
    expect(shape.lastValueMinor).toBe(42000)
  })
})

describe('shapeTrendLine', () => {
  it('returns an empty shape for an empty series', () => {
    expect(shapeTrendLine([])).toEqual({ path: '', areaPath: '', points: [], minValueMinor: 0, maxValueMinor: 0 })
  })

  it('builds an M/L path and a closed area path', () => {
    const shape = shapeTrendLine(
      [
        { date: '2026-05-01', value_minor: 10000 },
        { date: '2026-06-01', value_minor: 19000 },
        { date: '2026-07-01', value_minor: 28000 },
      ],
      100,
      50,
    )
    expect(shape.path.startsWith('M0.00,50.00')).toBe(true)
    expect(shape.path).toContain('L100.00,0.00')
    expect(shape.areaPath.endsWith('Z')).toBe(true)
    expect(shape.areaPath).toContain('L100.00,50') // closes down to the bottom edge
    expect(shape.minValueMinor).toBe(10000)
    expect(shape.maxValueMinor).toBe(28000)
    expect(shape.points).toHaveLength(3)
  })

  it('does not force the y-domain to start at zero (trend lines may zoom)', () => {
    const shape = shapeTrendLine(
      [
        { date: '2026-05-01', value_minor: 100000 },
        { date: '2026-06-01', value_minor: 100500 },
      ],
      100,
      50,
    )
    expect(shape.minValueMinor).toBe(100000)
    expect(shape.maxValueMinor).toBe(100500)
  })
})

describe('shapeTargetLineY', () => {
  it('maps a target onto the trend line y-domain', () => {
    const y = shapeTargetLineY(20000, 0, 40000, 100)
    expect(y).toBe(50) // halfway up
  })

  it('returns null for a degenerate (zero-range) domain', () => {
    expect(shapeTargetLineY(100, 500, 500, 100)).toBeNull()
  })
})

describe('shapeGoalBar', () => {
  it('fills proportionally to target', () => {
    expect(shapeGoalBar(500000, 2000000, null)).toEqual({ fillPct: 0.25, projectedPct: null })
  })

  it('clamps fill above 100% (over-funded goal)', () => {
    expect(shapeGoalBar(3000000, 2000000, null).fillPct).toBe(1)
  })

  it('clamps a negative-effective current to zero', () => {
    expect(shapeGoalBar(-100, 2000000, null).fillPct).toBe(0)
  })

  it('positions the projection marker and clamps it too', () => {
    expect(shapeGoalBar(500000, 2000000, 1000000).projectedPct).toBe(0.5)
    expect(shapeGoalBar(500000, 2000000, 5000000).projectedPct).toBe(1)
    expect(shapeGoalBar(500000, 2000000, -1000000).projectedPct).toBe(0)
  })

  it('zero fill for an open-ended (null target) goal', () => {
    expect(shapeGoalBar(50000, null, null)).toEqual({ fillPct: 0, projectedPct: null })
  })
})
