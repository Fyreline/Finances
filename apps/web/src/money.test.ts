import { describe, expect, it } from 'vitest'
import { formatMinor, formatMinorSigned, formatMinorWhole, formatMinorWholeCeil, formatPercent, poundsToMinor, MONEY_CLASS } from './money'

describe('formatMinor', () => {
  it('formats a simple positive amount', () => {
    expect(formatMinor(123456)).toBe('£1,234.56')
  })

  it('formats zero', () => {
    expect(formatMinor(0)).toBe('£0.00')
  })

  it('pads single-digit pence', () => {
    expect(formatMinor(100005)).toBe('£1,000.05')
  })

  it('uses a minus sign, never parentheses, for negative amounts', () => {
    expect(formatMinor(-4899)).toBe('-£48.99')
  })

  it('comma-groups thousands', () => {
    expect(formatMinor(2000000)).toBe('£20,000.00')
  })

  it('rounds non-integer pence input defensively', () => {
    expect(formatMinor(150.6)).toBe('£1.51')
  })
})

describe('formatMinorSigned', () => {
  it('prefixes a plus sign on positive amounts', () => {
    expect(formatMinorSigned(50000)).toBe('+£500.00')
  })

  it('leaves negative amounts with just the minus sign', () => {
    expect(formatMinorSigned(-50000)).toBe('-£500.00')
  })

  it('adds no sign for zero', () => {
    expect(formatMinorSigned(0)).toBe('£0.00')
  })
})

describe('formatMinorWhole', () => {
  it('drops pence and comma-groups', () => {
    expect(formatMinorWhole(2000000)).toBe('£20,000')
  })

  it('rounds to the nearest pound', () => {
    expect(formatMinorWhole(2050)).toBe('£21') // 20.50 -> rounds to 21
    expect(formatMinorWhole(2049)).toBe('£20') // 20.49 -> rounds to 20
  })

  it('keeps the minus sign for negative amounts', () => {
    expect(formatMinorWhole(-150000)).toBe('-£1,500')
  })
})

describe('formatMinorWholeCeil', () => {
  it('rounds up even a small fraction of a pound — never flatters', () => {
    // £862.20 -> a goal's required-per-month must never round down to
    // £862 (docs/ARCHITECTURE.md §6 "ceil on required-per-month").
    expect(formatMinorWholeCeil(86220)).toBe('£863')
  })

  it('leaves an already-whole pound amount unchanged', () => {
    expect(formatMinorWholeCeil(150000)).toBe('£1,500')
  })

  it('still ceils just 1p over a whole pound', () => {
    expect(formatMinorWholeCeil(150001)).toBe('£1,501')
  })

  it('keeps the minus sign for negative amounts (ceils the magnitude)', () => {
    expect(formatMinorWholeCeil(-86220)).toBe('-£863')
  })

  it('handles zero', () => {
    expect(formatMinorWholeCeil(0)).toBe('£0')
  })
})

describe('formatPercent', () => {
  it('renders one decimal place max', () => {
    expect(formatPercent(0.061)).toBe('6.1%')
    expect(formatPercent(0.06)).toBe('6.0%')
  })
})

describe('poundsToMinor', () => {
  it('converts a float pounds value to integer pence at the client edge', () => {
    expect(poundsToMinor(1234.56)).toBe(123456)
    expect(poundsToMinor(300)).toBe(30000)
  })
})

describe('MONEY_CLASS', () => {
  it('is the shared mono tabular-nums class string', () => {
    expect(MONEY_CLASS).toBe('font-mono tabular-nums')
  })
})
