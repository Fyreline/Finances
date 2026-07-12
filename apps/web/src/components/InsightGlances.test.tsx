import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import type { Recurring, RecurringList } from '../api'
import { pickNextRecurring, RecurringGlance } from './InsightGlances'

// Pure-selection tests (docs/CLAUDE.md: pure-function tests preferred) plus one
// raw react-dom render to prove the amount now shows in the glance — no
// @testing-library dependency, matching AppErrorBoundary.test.tsx.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function mk(over: Partial<Recurring>): Recurring {
  return {
    id: 1,
    label: 'Item',
    cadence: 'monthly',
    typical_amount_minor: -999,
    amount_drift_pct: 0,
    first_seen: '2026-01-01',
    last_seen: '2026-07-01',
    next_expected: '2026-08-01',
    occurrences: 5,
    status: 'active',
    user_verdict: null,
    confidence: 0.9,
    cancel_candidate: false,
    monthly_equivalent_minor: -999,
    old_amount_minor: -999,
    new_amount_minor: -999,
    ...over,
  }
}

describe('pickNextRecurring', () => {
  it('prefers an active pattern over a lapsed one with an earlier next_expected', () => {
    // The lapsed transfer is chronologically sooner, but its stale next_expected
    // is the least relevant thing to headline (docs/phases/PHASE-14 item 2).
    const lapsedSoon = mk({ label: 'Old transfer', status: 'lapsed', next_expected: '2026-08-01' })
    const activeLater = mk({ label: 'Netflix', status: 'active', next_expected: '2026-08-20' })
    expect(pickNextRecurring([lapsedSoon, activeLater])?.label).toBe('Netflix')
  })

  it('falls back to the soonest when nothing is active', () => {
    const a = mk({ label: 'A', status: 'lapsed', next_expected: '2026-09-01' })
    const b = mk({ label: 'B', status: 'lapsed', next_expected: '2026-08-01' })
    expect(pickNextRecurring([a, b])?.label).toBe('B')
  })

  it('excludes dismissed items (cancelled / not a subscription)', () => {
    const cancelled = mk({ label: 'X', status: 'active', next_expected: '2026-08-01', user_verdict: 'cancelled' })
    const notRecurring = mk({ label: 'Z', status: 'active', next_expected: '2026-08-02', user_verdict: 'not_recurring' })
    const keep = mk({ label: 'Y', status: 'active', next_expected: '2026-08-20' })
    expect(pickNextRecurring([cancelled, notRecurring, keep])?.label).toBe('Y')
  })
})

let container: HTMLDivElement | null = null
let root: Root | null = null

afterEach(() => {
  if (root) act(() => root!.unmount())
  container?.remove()
  container = null
  root = null
})

describe('RecurringGlance', () => {
  it('shows the amount on the next line — how much, for what, when', () => {
    const data: RecurringList = {
      recurring: [mk({ label: 'Netflix', typical_amount_minor: -999, next_expected: '2026-08-03' })],
      totals: { monthly_committed_minor: 21450 },
    }
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => root!.render(<RecurringGlance data={data} />))
    const text = container.textContent ?? ''
    expect(text).toContain('Netflix')
    expect(text).toContain('£9.99') // the amount — previously missing
    expect(text).toContain('£214.50') // monthly committed total
  })
})
