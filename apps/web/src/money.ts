// Money formatting — the ONLY place display formatting happens
// (docs/ARCHITECTURE.md §6). Every amount in Kakeibo is integer pence,
// signed from the user's perspective (negative = out); this module turns that
// into `£1,234.56` with a minus sign (never parentheses), and exposes the
// mono/tabular-nums class every money figure in the UI uses
// (docs/DESIGN.md §2c.4).

/** `font-mono tabular-nums` — apply to every element that renders a money
 * figure (tiles, tables, chart labels) so digits align in fixed-width
 * columns (docs/DESIGN.md §2c.4 / §6). */
export const MONEY_CLASS = 'font-mono tabular-nums'

/** Format integer pence as `£1,234.56` (or `-£1,234.56` for a negative
 * amount — a minus sign, never parentheses, docs/ARCHITECTURE.md §6). */
export function formatMinor(amountMinor: number): string {
  if (!Number.isFinite(amountMinor)) return '£0.00'
  const rounded = Math.round(amountMinor)
  const sign = rounded < 0 ? '-' : ''
  const abs = Math.abs(rounded)
  const pounds = Math.floor(abs / 100)
  const pence = abs % 100
  const poundsStr = pounds.toLocaleString('en-GB')
  return `${sign}£${poundsStr}.${pence.toString().padStart(2, '0')}`
}

/** Same as formatMinor but with a leading `+` on positive amounts — used
 * for income rows in TransactionTable (docs/DESIGN.md §4e: "income prefixed
 * `+` in gain"). Zero renders with no sign. */
export function formatMinorSigned(amountMinor: number): string {
  const rounded = Math.round(amountMinor)
  if (rounded > 0) return `+${formatMinor(rounded)}`
  return formatMinor(rounded)
}

/** Whole pounds only, no pence, still comma-grouped — for large headline
 * figures where pence would be visual noise (e.g. a goal target). Still
 * routes through formatMinor's rounding/sign rules. */
export function formatMinorWhole(amountMinor: number): string {
  const rounded = Math.round(amountMinor)
  const sign = rounded < 0 ? '-' : ''
  const pounds = Math.round(Math.abs(rounded) / 100)
  return `${sign}£${pounds.toLocaleString('en-GB')}`
}

/** One decimal place max (docs/ARCHITECTURE.md §6: "percentages: one
 * decimal place max"). */
export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`
}

/** Whole pounds, rounding UP — for the one class of figure that must never
 * flatter the user even at the final display step: a goal's
 * required-per-month / catch-up-per-month (docs/ARCHITECTURE.md §6:
 * "'on track' maths rounds *against* the user (ceil on required-per-month)
 * so the app never flatters"). The server already ceils to the pence
 * (`engines/goals.py`), but e.g. a pence value ending in `.20` still needs a
 * second ceil at the pence-to-whole-pound step — `formatMinorWhole`'s
 * ordinary round-half would silently understate any sub-50p fraction by
 * rounding it down, exactly the flattering this rule forbids. Every OTHER
 * whole-pound figure (a balance, a target) should keep using
 * `formatMinorWhole`; this formatter is only for figures carrying a "you
 * need at least this much" meaning. */
export function formatMinorWholeCeil(amountMinor: number): string {
  const rounded = Math.round(amountMinor)
  const sign = rounded < 0 ? '-' : ''
  const pounds = Math.ceil(Math.abs(rounded) / 100)
  return `${sign}£${pounds.toLocaleString('en-GB')}`
}

/** Convert a pounds.pence number (e.g. from a form input, or a provider
 * float) to integer pence — the ONE place a float is allowed to touch money,
 * at the client edge, immediately converted (docs/ARCHITECTURE.md §6 mirrors
 * the server's `round(x * 100)` convention for T212 floats). */
export function poundsToMinor(pounds: number): number {
  return Math.round(pounds * 100)
}
