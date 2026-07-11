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

import type { AffordabilityVerdict, EmergencyFundVerdict, OccasionVerdict } from '../api'

// docs/phases/PHASE-9-personal-goals.md §2 — every band, including the
// lowest, is calm information (kraft/oat), never crimson-as-alarm
// (docs/PLAN.md §6 rule 8).
export const EMERGENCY_FUND_LABEL: Record<EmergencyFundVerdict, string> = {
  unknown: 'not enough data yet',
  building_from_scratch: 'building from scratch',
  below_guide: 'below the usual guide',
  within_range: 'within the usual range',
  well_covered: 'well covered',
}

export const EMERGENCY_FUND_STYLE: Record<EmergencyFundVerdict, string> = {
  unknown: 'bg-oat text-ink-mid',
  building_from_scratch: 'bg-kraft/20 text-clay-deep',
  below_guide: 'bg-kraft/20 text-clay-deep',
  within_range: 'bg-olive/15 text-olive',
  well_covered: 'bg-olive/15 text-olive',
}

// docs/phases/PHASE-9-personal-goals.md §5 — the affordability check's
// verdict vocabulary; "not_yet" is a nudge (kraft), never a red no.
export const AFFORDABILITY_LABEL: Record<AffordabilityVerdict, string> = {
  unknown: 'not enough set up yet',
  fits_now: 'yes, this fits',
  not_yet: 'not yet',
  fits_from_spare_cash: 'fits from spare cash',
}

export const AFFORDABILITY_STYLE: Record<AffordabilityVerdict, string> = {
  unknown: 'bg-oat text-ink-mid',
  fits_now: 'bg-olive/15 text-olive',
  not_yet: 'bg-kraft/20 text-clay-deep',
  fits_from_spare_cash: 'bg-oat text-ink-mid',
}

// docs/PLAN.md §3 row 10 — over-limit is information, not guilt.
export const OCCASION_LABEL: Record<OccasionVerdict, string> = {
  no_limit_set: 'no limit set',
  under_limit: 'under limit',
  over_limit: 'over limit',
}

export const OCCASION_STYLE: Record<OccasionVerdict, string> = {
  no_limit_set: 'bg-oat text-ink-mid',
  under_limit: 'bg-olive/15 text-olive',
  over_limit: 'bg-kraft/20 text-clay-deep',
}
