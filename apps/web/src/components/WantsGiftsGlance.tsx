import type { WantsList, GiftOccasionsList } from '../api'
import { MONEY_CLASS } from '../money'

/** "Wants & gifts" bubble's collapsed glance (goals 10-11, docs/phases/
 * PHASE-9-personal-goals.md §4-5) — item count + how many currently look
 * affordable, and occasion count with any over-limit ones flagged as calm
 * information (never guilt, docs/PLAN.md §6 rule 8). */
export function WantsGiftsGlance({ wants, gifts }: { wants: WantsList; gifts: GiftOccasionsList }) {
  const unbought = wants.wants.filter((w) => !w.bought)
  const affordableNow = unbought.filter((w) => w.affordability?.verdict === 'fits_now').length
  const overLimitCount = gifts.occasions.filter((o) => o.verdict === 'over_limit').length

  return (
    <>
      <span className={`text-2xl ${MONEY_CLASS} text-ink`}>{unbought.length}</span>
      <p className="font-serif text-sm text-ink-mid">
        {unbought.length === 1 ? 'item on your list' : 'items on your list'}
        {unbought.length > 0 && ` · ${affordableNow} fit now`}
      </p>
      {gifts.occasions.length > 0 && (
        <span className="font-mono text-[11px] text-ink-soft">
          {gifts.occasions.length} occasion{gifts.occasions.length === 1 ? '' : 's'}
          {overLimitCount > 0 && ` · ${overLimitCount} over limit`}
        </span>
      )}
    </>
  )
}
