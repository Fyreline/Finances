import type { ComponentType, ReactNode } from 'react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Bubble } from './Bubble'
import { BraceConnector } from './BraceConnector'
import { DepositGlance, RebuildGlance } from './GoalGlance'
import { SafeToSpendGlance } from './SafeToSpendGlance'
import { RecurringGlance, SpendingGlance, TaxGlance } from './InsightGlances'
import { DealsGlance } from './DealsGlance'
import { NetWorthGlance } from './NetWorthGlance'
import { WantsGiftsGlance } from './WantsGiftsGlance'
import type { BubblesSummary } from '../api'
import { SettleContext } from '../charts/settle'
import { SafeToSpendDetail } from './details/SafeToSpendDetail'
import { DepositDetail } from './details/DepositDetail'
import { RebuildDetail } from './details/RebuildDetail'
import { SpendingDetail } from './details/SpendingDetail'
import { RecurringDetail } from './details/RecurringDetail'
import { TaxDetail } from './details/TaxDetail'
import { DealsDetail } from './details/DealsDetail'
import { NetWorthDetail } from './details/NetWorthDetail'
import { WantsGiftsDetail } from './details/WantsGiftsDetail'

interface BubbleSpec {
  key: string
  title: string
  hero?: boolean
  lines: string[]
  Detail: ComponentType
  glance?: ReactNode
}

// docs/DESIGN.md §3b — the canonical bubble roster. S1 (net worth), S2
// (emergency fund, folded into the Net Worth detail) and S4 (contractor
// gap, same) were accepted and built in Phase 9; S3 (splits) is still
// undecided and stays unbuilt. Goals 10-11 (gift budgets + personal wants)
// share one "Wants & gifts" bubble (docs/phases/PHASE-9-personal-goals.md).
// Every bubble renders in its `not_configured` setup state until real data
// exists — no fake numbers (docs/DESIGN.md §3b, docs/PLAN.md §6). The whole
// roster reads from the one `GET /api/summary/bubbles` fetch (Phase 7) —
// each bubble's `glance` is merged in below the moment its data exists.
const BUBBLE_SPECS: BubbleSpec[] = [
  {
    key: 'safe-to-spend',
    title: 'Safe to spend',
    hero: true,
    lines: ['Tell Kakeibo about payday and take-home pay to unlock this.'],
    Detail: SafeToSpendDetail,
  },
  {
    key: 'deposit',
    title: 'House deposit',
    lines: ['Set a target and deadline in local config to begin.'],
    Detail: DepositDetail,
  },
  {
    key: 'rebuild',
    title: 'T212 rebuild',
    lines: ['Nothing synced yet — connect Trading 212 to begin.'],
    Detail: RebuildDetail,
  },
  {
    key: 'spending',
    title: 'Spending this month',
    lines: ['Nothing synced yet — connect Starling to begin.'],
    Detail: SpendingDetail,
  },
  {
    key: 'recurring',
    title: 'Recurring',
    lines: ['Nothing synced yet — connect Starling to begin.'],
    Detail: RecurringDetail,
  },
  {
    key: 'tax',
    title: 'Tax year',
    lines: ['No rental documents reviewed yet.'],
    Detail: TaxDetail,
  },
  {
    key: 'deals',
    title: 'Savings deals',
    lines: ['No research run yet — rates arrive with the first research pass.'],
    Detail: DealsDetail,
  },
  {
    key: 'net-worth',
    title: 'Net worth',
    lines: ['No accounts included in net worth yet.'],
    Detail: NetWorthDetail,
  },
  {
    key: 'wants-gifts',
    title: 'Wants & gifts',
    lines: ['Nothing on your wants list or gift occasions yet.'],
    Detail: WantsGiftsDetail,
  },
]

// docs/DESIGN.md §3b: "1 column <640px, 2 columns <1024px, 3 columns >=1024px".
function calcColumns(): number {
  if (typeof window === 'undefined') return 3
  const w = window.innerWidth
  if (w >= 1024) return 3
  if (w >= 640) return 2
  return 1
}

function useColumns(): number {
  const [columns, setColumns] = useState(calcColumns)
  useEffect(() => {
    const onResize = () => setColumns(calcColumns())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return columns
}

function useIsDesktop(): boolean {
  return useColumns() === 3
}

/** Reads/writes the active bubble from the URL hash (`#deposit`) so reload
 * restores the expanded state (docs/DESIGN.md §3c "deep-linking"). A `/`
 * segment is reserved for internal-tab state (`#spending/tips`) — this hook
 * only parses the bubble-key half; SpendingDetail/TaxDetail layer tab state
 * on top without changing this contract. */
function useHashRoute(): [string | null, (key: string | null) => void] {
  const parse = () => {
    const raw = window.location.hash.replace(/^#/, '')
    return raw ? raw.split('/')[0] : null
  }
  const [active, setActive] = useState<string | null>(parse)

  useEffect(() => {
    const onHashChange = () => setActive(parse())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const setKey = useCallback((key: string | null) => {
    if (key) {
      window.location.hash = key
    } else {
      history.replaceState(null, '', window.location.pathname + window.location.search)
    }
    setActive(key)
  }, [])

  return [active, setKey]
}

function groupRows(items: BubbleSpec[], columns: number): BubbleSpec[][] {
  const rows: BubbleSpec[][] = []
  for (let i = 0; i < items.length; i += columns) {
    rows.push(items.slice(i, i + columns))
  }
  return rows
}

/** Wraps a detail view and tells its charts when the container has finished
 * its open transition — "charts mount after the panel settles, then run
 * their ≤600ms draw-in" (docs/DESIGN.md §3c). The chart primitives read
 * `SettleContext` and hold their draw-in until it flips true; their SVG
 * boxes reserve space from the first frame so nothing thrashes layout. */
function DetailPanel({ bubble, settled }: { bubble: BubbleSpec; settled: boolean }) {
  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panelRef.current?.focus()
  }, [bubble.key])
  const Detail = bubble.Detail
  return (
    <div
      ref={panelRef}
      tabIndex={-1}
      role="region"
      aria-label={`${bubble.title} detail`}
      className="rounded-b-lg border border-t-0 border-liquid bg-paper-mid p-5 outline-none"
    >
      <SettleContext.Provider value={settled}>
        <Detail />
      </SettleContext.Provider>
    </div>
  )
}

function BubbleRow({
  bubbles,
  activeKey,
  onToggle,
  isDesktop,
  bubbleRefs,
}: {
  bubbles: BubbleSpec[]
  activeKey: string | null
  onToggle: (key: string) => void
  isDesktop: boolean
  bubbleRefs: { current: Map<string, HTMLButtonElement> }
}) {
  const rowRef = useRef<HTMLDivElement>(null)
  const activeInRow = bubbles.find((b) => b.key === activeKey) ?? null
  const [peak, setPeak] = useState<{ width: number; x: number } | null>(null)
  const [settled, setSettled] = useState(false)

  useEffect(() => {
    setSettled(false)
  }, [activeInRow?.key])

  useLayoutEffect(() => {
    if (!activeInRow || !isDesktop) {
      setPeak(null)
      return
    }
    const measure = () => {
      const row = rowRef.current
      const btn = bubbleRefs.current.get(activeInRow.key)
      if (!row || !btn) return
      const rowRect = row.getBoundingClientRect()
      const btnRect = btn.getBoundingClientRect()
      setPeak({ width: rowRect.width, x: btnRect.left + btnRect.width / 2 - rowRect.left })
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [activeInRow, isDesktop, bubbleRefs])

  return (
    <div>
      <div ref={rowRef} className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {bubbles.map((b) => (
          <Bubble
            key={b.key}
            ref={(el) => {
              if (el) bubbleRefs.current.set(b.key, el)
              else bubbleRefs.current.delete(b.key)
            }}
            title={b.title}
            lines={b.lines}
            hero={b.hero}
            active={b.key === activeKey}
            onClick={() => onToggle(b.key)}
          >
            {b.glance}
          </Bubble>
        ))}
      </div>
      {isDesktop && (
        <AnimatePresence initial={false}>
          {activeInRow && peak && (
            <motion.div
              key={activeInRow.key}
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              style={{ overflow: 'hidden' }}
              onAnimationComplete={(definition) => {
                // Fires for enter and exit alike — only the open target
                // means "settled" (docs/DESIGN.md §3c: charts draw in after
                // the panel finishes moving; instant under reduced motion,
                // where MotionConfig makes this fire immediately).
                if (typeof definition === 'object' && definition !== null && 'opacity' in definition && definition.opacity === 1) {
                  setSettled(true)
                }
              }}
            >
              <BraceConnector width={peak.width} peakX={peak.x} />
              <DetailPanel bubble={activeInRow} settled={settled} />
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  )
}

function MobileSheet({ bubble, onClose }: { bubble: BubbleSpec | null; onClose: () => void }) {
  const sheetRef = useRef<HTMLDivElement>(null)
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    if (bubble) sheetRef.current?.focus()
    setSettled(false)
  }, [bubble])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && bubble) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [bubble, onClose])

  return (
    <AnimatePresence>
      {bubble && (
        <>
          <motion.div
            className="fixed inset-0 z-30 bg-ink/30"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={sheetRef}
            tabIndex={-1}
            role="region"
            aria-label={`${bubble.title} detail`}
            className="fixed inset-x-0 bottom-0 z-40 max-h-[85vh] overflow-y-auto rounded-t-lg bg-paper p-5 shadow-float outline-none"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ duration: 0.26, ease: 'easeOut' }}
            onAnimationComplete={(definition) => {
              if (typeof definition === 'object' && definition !== null && 'y' in definition && definition.y === 0) {
                setSettled(true)
              }
            }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.4 }}
            onDragEnd={(_event, info) => {
              // Swipe-dismiss on either a decisive flick (velocity) or a
              // long deliberate drag (offset) — docs/DESIGN.md §3c /
              // docs/phases/PHASE-7-dashboard.md item 2 "swipe-dismiss
              // velocity".
              if (info.offset.y > 120 || info.velocity.y > 500) onClose()
            }}
          >
            <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line-strong" aria-hidden />
            {/* The sheet header repeats the bubble's glance so context
                carries over (docs/DESIGN.md §3c mobile spec). */}
            <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">{bubble.title}</span>
            {bubble.glance && (
              <div className="mt-2 flex flex-col items-start gap-2 border-b border-line pb-3">{bubble.glance}</div>
            )}
            <div className="mt-3">
              <SettleContext.Provider value={settled}>
                <bubble.Detail />
              </SettleContext.Provider>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

/** THE screen — bubble grid + expand logic (docs/DESIGN.md §3, §3c). Bubbles
 * are the app's navigation; there is no tab bar. Desktop expands in-place
 * below the bubble's own row (brace-connected); mobile uses a full-height
 * bottom sheet. `#hash` deep-links restore the expanded state on reload.
 * The whole collapsed screen renders from the one `summary` payload
 * (docs/phases/PHASE-7-dashboard.md item 6) — detail panels fetch their own
 * richer data when opened. */
export function HomePage({
  summary,
  onPanelClose,
}: {
  summary: BubblesSummary | null
  /** Fired whenever the active detail panel transitions from open to closed
   * (docs/phases/PHASE-10-post-launch-fixes.md item 2) — App.tsx uses this
   * to refetch the one-fetch summary, since closing a panel is a natural
   * "data may have changed" moment (config saved, time passed). */
  onPanelClose?: () => void
}) {
  const [activeKey, setActiveKey] = useHashRoute()
  const isDesktop = useIsDesktop()
  const columns = useColumns()
  const bubbleRefs = useRef(new Map<string, HTMLButtonElement>())
  const prevActiveKey = useRef(activeKey)

  useEffect(() => {
    if (prevActiveKey.current !== null && activeKey === null) {
      onPanelClose?.()
    }
    prevActiveKey.current = activeKey
  }, [activeKey, onPanelClose])

  // Merge real glance content into each spec the moment its data exists in
  // the one-fetch payload (docs/DESIGN.md §3b collapsed content specs) —
  // otherwise the bubble keeps its calm serif setup state. Never both.
  const bubbles = useMemo<BubbleSpec[]>(() => {
    if (!summary) return BUBBLE_SPECS
    const goalsByKey = Object.fromEntries(summary.goals.map((g) => [g.key, g]))
    return BUBBLE_SPECS.map((spec) => {
      if (spec.key === 'safe-to-spend' && summary.safe_to_spend.safe_to_spend_minor !== null) {
        return { ...spec, glance: <SafeToSpendGlance data={summary.safe_to_spend} /> }
      }
      if (spec.key === 'deposit' && goalsByKey.house_deposit) {
        return { ...spec, glance: <DepositGlance goal={goalsByKey.house_deposit} /> }
      }
      if (spec.key === 'rebuild' && goalsByKey.t212_rebuild) {
        return { ...spec, glance: <RebuildGlance goal={goalsByKey.t212_rebuild} /> }
      }
      if (spec.key === 'spending' && summary.month_summary.categories.length > 0) {
        return { ...spec, glance: <SpendingGlance summary={summary.month_summary} tipCount={summary.tips_count} /> }
      }
      if (spec.key === 'recurring' && summary.recurring.recurring.length > 0) {
        return { ...spec, glance: <RecurringGlance data={summary.recurring} /> }
      }
      if (spec.key === 'tax') {
        const tax = summary.tax
        const titled = { ...spec, title: `Tax year ${tax.tax_year}` }
        // Glance only once there's something real to glance at — a profit
        // figure, a live estimate, or documents waiting (docs/DESIGN.md §3b
        // row 6); otherwise the setup line stands, never fake numbers.
        if (tax.profit_minor > 0 || tax.estimated_tax_minor !== null || tax.unreviewed_documents > 0) {
          return { ...titled, glance: <TaxGlance data={tax} /> }
        }
        return titled
      }
      if (spec.key === 'deals' && summary.deals.run && summary.deals.deals.length > 0) {
        return { ...spec, glance: <DealsGlance data={summary.deals} /> }
      }
      if (spec.key === 'net-worth' && summary.net_worth.by_account.length > 0) {
        return { ...spec, glance: <NetWorthGlance data={summary.net_worth} /> }
      }
      if (spec.key === 'wants-gifts' && (summary.wants.wants.length > 0 || summary.gifts.occasions.length > 0)) {
        return { ...spec, glance: <WantsGiftsGlance wants={summary.wants} gifts={summary.gifts} /> }
      }
      return spec
    })
  }, [summary])

  const hero = useMemo(() => bubbles.filter((b) => b.hero), [bubbles])
  const rest = useMemo(() => bubbles.filter((b) => !b.hero), [bubbles])
  const rows = useMemo(() => groupRows(rest, columns), [rest, columns])

  const toggle = useCallback(
    (key: string) => {
      setActiveKey(activeKey === key ? null : key)
    },
    [activeKey, setActiveKey],
  )

  const close = useCallback(() => {
    const key = activeKey
    setActiveKey(null)
    if (key) bubbleRefs.current.get(key)?.focus()
  }, [activeKey, setActiveKey])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && activeKey) close()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [activeKey, close])

  const activeBubble = bubbles.find((b) => b.key === activeKey) ?? null

  return (
    <div className="mx-auto w-full max-w-[72rem] space-y-4 px-5 pb-24 pt-8">
      <BubbleRow bubbles={hero} activeKey={activeKey} onToggle={toggle} isDesktop={isDesktop} bubbleRefs={bubbleRefs} />
      {rows.map((row) => (
        <BubbleRow
          key={row.map((b) => b.key).join('-')}
          bubbles={row}
          activeKey={activeKey}
          onToggle={toggle}
          isDesktop={isDesktop}
          bubbleRefs={bubbleRefs}
        />
      ))}

      {!isDesktop && <MobileSheet bubble={activeBubble} onClose={close} />}
    </div>
  )
}
