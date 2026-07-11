import { useEffect, useState } from 'react'
import { api, type GiftOccasion, type WantItem } from '../../api'
import { AFFORDABILITY_LABEL, AFFORDABILITY_STYLE, OCCASION_LABEL, OCCASION_STYLE } from '../../charts/verdict'
import { formatMinor, MONEY_CLASS, poundsToMinor } from '../../money'

type Tab = 'wants' | 'gifts'

const TABS: { key: Tab; label: string }[] = [
  { key: 'wants', label: 'Wants' },
  { key: 'gifts', label: 'Gifts' },
]

/** Internal tabs are a hash segment on top of the bubble key
 * (`#wants-gifts/gifts`), mirroring SpendingDetail's `useTabHash`
 * (docs/DESIGN.md §3c). */
function useTabHash(defaultTab: Tab): [Tab, (tab: Tab) => void] {
  const parse = (): Tab => {
    const raw = window.location.hash.replace(/^#/, '')
    const tab = raw.split('/')[1]
    return (TABS.some((t) => t.key === tab) ? tab : defaultTab) as Tab
  }
  const [tab, setTabState] = useState<Tab>(parse)

  useEffect(() => {
    const onHashChange = () => setTabState(parse())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setTab = (next: Tab) => {
    const bubbleKey = window.location.hash.replace(/^#/, '').split('/')[0] || 'wants-gifts'
    window.location.hash = `${bubbleKey}/${next}`
    setTabState(next)
  }
  return [tab, setTab]
}

/** A small pounds+pence text input that converts to minor pence on submit —
 * the one place a float legitimately touches money, at the form edge
 * (docs/ARCHITECTURE.md §6, `money.ts poundsToMinor`). */
function AddItemForm({ onAdd, placeholderLabel }: { onAdd: (label: string, priceMinor: number) => void; placeholderLabel: string }) {
  const [label, setLabel] = useState('')
  const [price, setPrice] = useState('')
  return (
    <form
      className="flex flex-wrap items-center gap-2 border-t border-line pt-3"
      onSubmit={(e) => {
        e.preventDefault()
        const pounds = Number(price)
        if (!label.trim() || !Number.isFinite(pounds) || pounds <= 0) return
        onAdd(label.trim(), poundsToMinor(pounds))
        setLabel('')
        setPrice('')
      }}
    >
      <input
        type="text"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder={placeholderLabel}
        className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2 py-1 text-[13px] text-ink outline-none focus-visible:border-clay/60"
      />
      <input
        type="number"
        inputMode="decimal"
        step="0.01"
        min="0"
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        placeholder="£"
        className={`w-20 rounded-md border border-line bg-paper px-2 py-1 text-[13px] text-ink outline-none focus-visible:border-clay/60 ${MONEY_CLASS}`}
      />
      <button
        type="submit"
        className="rounded-md border border-line px-2 py-1 text-[11px] text-ink-mid transition hover:bg-paper-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60"
      >
        Add
      </button>
    </form>
  )
}

function WantRow({ item, onBought, onDelete }: { item: WantItem; onBought: (id: number) => void; onDelete: (id: number) => void }) {
  return (
    <div className={`flex flex-wrap items-center gap-2 py-2.5 ${item.bought ? 'opacity-50' : ''}`}>
      <span className="flex-1 truncate text-[14px] text-ink">{item.label}</span>
      <span className={`text-[14px] ${MONEY_CLASS} text-ink`}>{formatMinor(item.price_minor)}</span>
      {item.affordability && (
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] ${AFFORDABILITY_STYLE[item.affordability.verdict]}`}
          title={item.affordability.detail}
        >
          {AFFORDABILITY_LABEL[item.affordability.verdict]}
        </span>
      )}
      {!item.bought && (
        <button
          type="button"
          onClick={() => onBought(item.id)}
          className="rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-mid transition hover:bg-paper-deep"
        >
          bought
        </button>
      )}
      <button
        type="button"
        onClick={() => onDelete(item.id)}
        className="rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-mid transition hover:bg-paper-deep"
      >
        remove
      </button>
    </div>
  )
}

function WantsTab() {
  const [items, setItems] = useState<WantItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .wants()
      .then((r) => setItems(r.wants))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load"))
  }
  useEffect(load, [])

  if (error) return <p className="text-[13px] text-ink-mid">{error}</p>
  if (!items) return <p className="font-mono text-[11px] text-ink-soft">Loading…</p>

  return (
    <div className="space-y-2">
      {items.length === 0 ? (
        <p className="font-serif text-[15px] text-ink-mid">Nothing on your wants list yet.</p>
      ) : (
        <div className="divide-y divide-line">
          {items.map((item) => (
            <WantRow
              key={item.id}
              item={item}
              onBought={(id) => api.patchWant(id, { bought: true }).then(load)}
              onDelete={(id) => api.deleteWant(id).then(load)}
            />
          ))}
        </div>
      )}
      <AddItemForm placeholderLabel="want" onAdd={(label, priceMinor) => api.createWant({ label, price_minor: priceMinor }).then(load)} />
    </div>
  )
}

function OccasionCard({ occasion, onReload }: { occasion: GiftOccasion; onReload: () => void }) {
  return (
    <div className="space-y-2 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-display text-base font-medium text-ink">{occasion.label}</h4>
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] ${OCCASION_STYLE[occasion.verdict]}`}
        >
          {OCCASION_LABEL[occasion.verdict]}
        </span>
      </div>
      <p className={`text-[13px] ${MONEY_CLASS} text-ink-mid`}>
        {formatMinor(occasion.spent_minor)} spent
        {occasion.limit_minor !== null && ` of ${formatMinor(occasion.limit_minor)} limit`}
      </p>
      {occasion.items.length > 0 && (
        <div className="divide-y divide-line">
          {occasion.items.map((item) => (
            <div key={item.id} className={`flex items-center gap-2 py-1.5 ${item.bought ? 'opacity-50' : ''}`}>
              <span className="flex-1 truncate text-[13px] text-ink">{item.label}</span>
              <span className={`text-[13px] ${MONEY_CLASS} text-ink`}>{formatMinor(item.price_minor)}</span>
              {!item.bought && (
                <button
                  type="button"
                  onClick={() => api.patchGiftItem(item.id, { bought: true }).then(onReload)}
                  className="rounded-md border border-line px-2 py-0.5 text-[10px] text-ink-mid transition hover:bg-paper-deep"
                >
                  bought
                </button>
              )}
              <button
                type="button"
                onClick={() => api.deleteGiftItem(item.id).then(onReload)}
                className="rounded-md border border-line px-2 py-0.5 text-[10px] text-ink-mid transition hover:bg-paper-deep"
              >
                remove
              </button>
            </div>
          ))}
        </div>
      )}
      <AddItemForm
        placeholderLabel="gift item"
        onAdd={(label, priceMinor) => api.createGiftItem(occasion.id, { label, price_minor: priceMinor }).then(onReload)}
      />
    </div>
  )
}

function AddOccasionForm({ onAdd }: { onAdd: (label: string, limitMinor: number | null) => void }) {
  const [label, setLabel] = useState('')
  const [limit, setLimit] = useState('')
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (!label.trim()) return
        const pounds = Number(limit)
        const limitMinor = limit.trim() && Number.isFinite(pounds) && pounds > 0 ? poundsToMinor(pounds) : null
        onAdd(label.trim(), limitMinor)
        setLabel('')
        setLimit('')
      }}
    >
      <input
        type="text"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder="occasion"
        className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2 py-1 text-[13px] text-ink outline-none focus-visible:border-clay/60"
      />
      <input
        type="number"
        inputMode="decimal"
        step="0.01"
        min="0"
        value={limit}
        onChange={(e) => setLimit(e.target.value)}
        placeholder="limit £ (optional)"
        className={`w-32 rounded-md border border-line bg-paper px-2 py-1 text-[13px] text-ink outline-none focus-visible:border-clay/60 ${MONEY_CLASS}`}
      />
      <button
        type="submit"
        className="rounded-md border border-line px-2 py-1 text-[11px] text-ink-mid transition hover:bg-paper-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60"
      >
        New occasion
      </button>
    </form>
  )
}

function GiftsTab() {
  const [occasions, setOccasions] = useState<GiftOccasion[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api
      .giftOccasions()
      .then((r) => setOccasions(r.occasions))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load"))
  }
  useEffect(load, [])

  if (error) return <p className="text-[13px] text-ink-mid">{error}</p>
  if (!occasions) return <p className="font-mono text-[11px] text-ink-soft">Loading…</p>

  return (
    <div className="space-y-3">
      {occasions.length === 0 ? (
        <p className="font-serif text-[15px] text-ink-mid">No gift occasions set up yet.</p>
      ) : (
        occasions.map((occasion) => <OccasionCard key={occasion.id} occasion={occasion} onReload={load} />)
      )}
      <AddOccasionForm onAdd={(label, limitMinor) => api.createGiftOccasion({ label, limit_minor: limitMinor }).then(load)} />
    </div>
  )
}

/** Goals 10-11 (docs/PLAN.md §3 rows 10-11, docs/phases/
 * PHASE-9-personal-goals.md §4-5) — one bubble, two tabs, sharing the
 * affordability mechanic rather than two separate systems. */
export function WantsGiftsDetail() {
  const [tab, setTab] = useTabHash('wants')

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Wants and gifts views" className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60 ${
              tab === t.key ? 'border-b-2 border-clay text-ink' : 'text-ink-soft hover:text-ink-mid'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'wants' && <WantsTab />}
      {tab === 'gifts' && <GiftsTab />}
    </div>
  )
}
