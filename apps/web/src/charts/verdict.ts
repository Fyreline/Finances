import type { GoalStatus } from '../api'

// docs/DESIGN.md §4c — kraft, not crimson: behind on a goal is a nudge, not
// a failure. Shared between GoalBar (detail view) and the bubble glance
// (collapsed view) so the verdict pill never drifts between the two.
export const GOAL_VERDICT_STYLE: Record<GoalStatus, string> = {
  on_track: 'bg-olive/15 text-olive',
  behind: 'bg-kraft/20 text-clay-deep',
  no_trend: 'bg-oat text-ink-mid',
}

export const GOAL_VERDICT_LABEL: Record<GoalStatus, string> = {
  on_track: 'on track',
  behind: 'behind',
  no_trend: 'no trend yet',
}

import type { BenchmarkBand } from '../api'

// docs/DESIGN.md §4d/§6 — benchmark verdict pills. Wording is exactly these
// three; "above average" is kraft (a nudge), never crimson, unless the value
// is `severe` (>1.5× the band) — the one place crimson is allowed here.
export const BENCHMARK_LABEL: Record<BenchmarkBand, string> = {
  maintainable: 'maintainable',
  average: 'average',
  above_average: 'above average',
}

export function benchmarkPillStyle(band: BenchmarkBand, severe: boolean): string {
  if (band === 'maintainable') return 'bg-olive/15 text-olive'
  if (band === 'average') return 'bg-oat text-ink-mid'
  return severe ? 'bg-over/15 text-over' : 'bg-kraft/20 text-clay-deep'
}
