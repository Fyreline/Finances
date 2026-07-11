import { useEffect, useState } from 'react'
import { api, type MonthSummary, type PeriodMode } from '../../api'
import { CategoryBreakdown } from '../CategoryBreakdown'
import { TipsList } from '../TipsList'
import { TransactionTable } from '../TransactionTable'

type Tab = 'breakdown' | 'transactions' | 'tips'

/** Current month as `YYYY-MM` in local (UK) time — `en-CA` yields
 * `YYYY-MM-DD` so the slice is stable. */
function currentMonth(): string {
  return new Date().toLocaleDateString('en-CA').slice(0, 7)
}

// Persist the spending-period framing across sessions — localStorage, matching
// the theme toggle's lightweight-persistence pattern (docs/phases/PHASE-12 §5b).
const PERIOD_MODE_KEY = 'kakeibo-spending-period-mode'
function loadPeriodMode(): PeriodMode {
  return (typeof localStorage !== 'undefined' && localStorage.getItem(PERIOD_MODE_KEY)) === 'payday'
    ? 'payday'
    : 'calendar'
}

const _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** `2026-07-09` → `9 Jul` — parsed by hand so no timezone can shift the day. */
function formatDayMonth(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${d} ${_MONTHS[m - 1]}`
}

const PERIOD_MODES: { key: PeriodMode; label: string }[] = [
  { key: 'calendar', label: 'This month' },
  { key: 'payday', label: 'Since payday' },
]

function PeriodToggle({ mode, onChange }: { mode: PeriodMode; onChange: (m: PeriodMode) => void }) {
  return (
    <div
      role="group"
      aria-label="Spending period"
      className="inline-flex overflow-hidden rounded-full border border-line"
    >
      {PERIOD_MODES.map((m) => (
        <button
          key={m.key}
          type="button"
          aria-pressed={mode === m.key}
          onClick={() => onChange(m.key)}
          className={`min-h-11 px-3.5 font-mono text-[11px] uppercase tracking-[0.08em] transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60 ${
            mode === m.key ? 'bg-clay/12 text-ink' : 'text-ink-soft hover:text-ink-mid'
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}

/** The one-line framing under the toggle: which window this breakdown covers,
 * so calendar and payday framings can never be misread for one another. */
function periodFraming(summary: MonthSummary): string {
  // Defensive against a briefly-stale backend during a deploy (the field may be
  // absent until com.kakeibo.api restarts) — default to the calendar framing
  // rather than throwing, per the 2026-07-11 missing-field incident lesson.
  if (summary.period_mode !== 'payday') return 'This calendar month'
  const { start, end } = summary.period ?? { start: null, end: null }
  if (!start || !end) return 'Since your last payday'
  const via = summary.payday_source === 'detected' ? ' · worked out from your history' : ''
  return `Since your last payday · ${formatDayMonth(start)} – ${formatDayMonth(end)}${via}`
}

function BreakdownTab({ month, onSelectCategory }: { month: string; onSelectCategory: (key: string) => void }) {
  const [periodMode, setPeriodMode] = useState<PeriodMode>(loadPeriodMode)
  const [summary, setSummary] = useState<MonthSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    setSummary(null)
    setError(null)
    api
      .monthSummary(month, periodMode)
      .then((s) => !cancelled && setSummary(s))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Couldn't load"))
    return () => {
      cancelled = true
    }
  }, [month, periodMode])

  const changeMode = (m: PeriodMode) => {
    if (typeof localStorage !== 'undefined') localStorage.setItem(PERIOD_MODE_KEY, m)
    setPeriodMode(m)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PeriodToggle mode={periodMode} onChange={changeMode} />
        {summary && (
          <span className="font-mono text-[11px] text-ink-soft">{periodFraming(summary)}</span>
        )}
      </div>
      {error ? (
        <p className="text-[13px] text-ink-mid">{error}</p>
      ) : !summary ? (
        <p className="font-mono text-[11px] text-ink-soft">Loading…</p>
      ) : (summary.setup_missing?.length ?? 0) > 0 ? (
        <p className="font-serif text-base text-ink-mid">
          Set your payday, or let a couple of months of salary land, to see spending since your last payday. The
          calendar-month view works now.
        </p>
      ) : (
        <CategoryBreakdown summary={summary} onSelectCategory={onSelectCategory} />
      )}
    </div>
  )
}

const TABS: { key: Tab; label: string }[] = [
  { key: 'breakdown', label: 'Breakdown' },
  { key: 'transactions', label: 'Transactions' },
  { key: 'tips', label: 'Tips' },
]

/** Internal tabs are a hash segment on top of the bubble key
 * (`#spending/transactions`) — docs/DESIGN.md §3c, and HomePage's
 * `useHashRoute` deliberately only parses the bubble-key half so a later
 * phase (this one) can add tab state without touching that contract. */
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
    const bubbleKey = window.location.hash.replace(/^#/, '').split('/')[0] || 'spending'
    window.location.hash = `${bubbleKey}/${next}`
    setTabState(next)
  }

  return [tab, setTab]
}

export function SpendingDetail() {
  // All three tabs are live as of Phase 4; Breakdown is the natural landing
  // tab for the Spending bubble (docs/DESIGN.md §3b row 4).
  const [tab, setTab] = useTabHash('breakdown')
  const month = currentMonth()
  // Plain state, not hash-synced — matches TransactionTable's OWN filters
  // (month/category/q), which are plain useState too
  // (docs/phases/PHASE-10-post-launch-fixes.md item 5). Only feeds
  // TransactionTable's `initialFilters` on the mount that follows a category
  // click; cleared on any switch away from Transactions so a later, unrelated
  // visit never carries a stale filter forward.
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)

  const changeTab = (next: Tab) => {
    if (next !== 'transactions') setSelectedCategory(null)
    setTab(next)
  }

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Spending views" className="flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => changeTab(t.key)}
            className={`px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60 ${
              tab === t.key ? 'border-b-2 border-clay text-ink' : 'text-ink-soft hover:text-ink-mid'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'breakdown' && (
        <BreakdownTab
          month={month}
          onSelectCategory={(key) => {
            setSelectedCategory(key)
            setTab('transactions')
          }}
        />
      )}
      {tab === 'transactions' && (
        <TransactionTable initialFilters={selectedCategory ? { category: selectedCategory } : undefined} />
      )}
      {tab === 'tips' && <TipsList period={month} />}
    </div>
  )
}
