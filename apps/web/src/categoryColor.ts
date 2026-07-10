// Stable category viz_slot -> Aizome viz token mapping (docs/DESIGN.md §2b).
// `categories.viz_slot` (1..8, docs/DATA_MODEL.md §3) is assigned once in
// the server's category seed and never reshuffled — this is the one place
// that turns a slot number into a Tailwind class, so TransactionTable's
// category chips and any later chart (Phase 7) draw from the same source.
//
// Class names are written out literally (not built via template-string
// interpolation) so Tailwind's build-time class scanner can find them —
// a computed `bg-viz-${n}` string would never be generated (docs/DESIGN.md
// §1: "a hex in a component is a review-blocker" — the same "must be
// statically visible" constraint applies to token-derived classes here).
const SLOT_TO_DOT_CLASS: Record<number, string> = {
  1: 'bg-viz-5', // housing & bills -> steel blue
  2: 'bg-viz-6', // groceries -> hanko crimson
  3: 'bg-viz-7', // eating out -> mint teal
  4: 'bg-viz-8', // fun & subscriptions -> plum
  5: 'bg-viz-1', // transport -> pale cyan
  6: 'bg-viz-3', // shopping & gifts -> sakura
  7: 'bg-viz-4', // holidays -> sand
  8: 'bg-viz-2', // everything else -> pale mint
}

/** Tailwind background class for a category's viz_slot; a neutral `cloud`
 * fallback for uncategorised transactions (`viz_slot: null`) or an
 * unrecognised slot number. */
export function categoryDotClass(vizSlot: number | null): string {
  if (vizSlot === null) return 'bg-cloud'
  return SLOT_TO_DOT_CLASS[vizSlot] ?? 'bg-cloud'
}

// Slots whose token is one of the PALE viz colours (viz-1..4). Pale tokens
// are fill-only and must always carry a 1px `line-strong` outline so the
// shape stays legible on paper in both themes (docs/DESIGN.md §2c.1).
const PALE_SLOTS = new Set([5, 6, 7, 8])

/** Like `categoryDotClass`, plus the mandatory §2c.1 outline when the slot's
 * token is pale — use this for anything filled with a category colour (dots,
 * chips, bars); the saturated slots (viz-5..8) need no outline and get none. */
export function categoryChipClass(vizSlot: number | null): string {
  const base = categoryDotClass(vizSlot)
  if (vizSlot !== null && PALE_SLOTS.has(vizSlot)) return `${base} border border-line-strong`
  return base
}
