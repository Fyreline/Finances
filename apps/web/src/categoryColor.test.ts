import { describe, expect, it } from 'vitest'
import { categoryChipClass, categoryDotClass } from './categoryColor'

describe('categoryDotClass', () => {
  it('maps each documented slot to its DESIGN.md §2b viz token', () => {
    expect(categoryDotClass(1)).toBe('bg-viz-5') // housing & bills
    expect(categoryDotClass(2)).toBe('bg-viz-6') // groceries
    expect(categoryDotClass(3)).toBe('bg-viz-7') // eating out
    expect(categoryDotClass(4)).toBe('bg-viz-8') // fun & subscriptions
    expect(categoryDotClass(5)).toBe('bg-viz-1') // transport
    expect(categoryDotClass(6)).toBe('bg-viz-3') // shopping & gifts
    expect(categoryDotClass(7)).toBe('bg-viz-4') // holidays
    expect(categoryDotClass(8)).toBe('bg-viz-2') // everything else
  })

  it('falls back to a neutral class for uncategorised transactions', () => {
    expect(categoryDotClass(null)).toBe('bg-cloud')
  })

  it('falls back to a neutral class for an unrecognised slot number', () => {
    expect(categoryDotClass(99)).toBe('bg-cloud')
  })
})

describe('categoryChipClass', () => {
  it('adds the §2c.1 line-strong outline to pale slots only', () => {
    // saturated slots (viz-5..8): no outline
    for (const slot of [1, 2, 3, 4]) {
      expect(categoryChipClass(slot)).toBe(categoryDotClass(slot))
    }
    // pale slots (viz-1..4): fill-only, always outlined
    for (const slot of [5, 6, 7, 8]) {
      expect(categoryChipClass(slot)).toBe(`${categoryDotClass(slot)} border border-line-strong`)
    }
  })

  it('leaves the neutral fallback un-outlined', () => {
    expect(categoryChipClass(null)).toBe('bg-cloud')
    expect(categoryChipClass(99)).toBe('bg-cloud')
  })
})
