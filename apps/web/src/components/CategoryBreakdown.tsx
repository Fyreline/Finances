import type { MonthCategory, MonthSummary } from '../api'
import { categoryChipClass } from '../categoryColor'
import { useBarFill } from '../charts/useBarFill'
import { BENCHMARK_LABEL, benchmarkPillStyle } from '../charts/verdict'
import { formatMinor, MONEY_CLASS } from '../money'

function benchmarkTooltip(cat: MonthCategory): string {
  if (!cat.benchmark) return ''
  const [lo, hi] = cat.benchmark.band_bounds_minor
  // Heuristic framing is mandatory on every benchmark figure (docs/API.md §6b).
  return `Roughly typical ${formatMinor(lo)}–${formatMinor(hi)}/mo · rough ONS-derived estimate, as of ${cat.benchmark.as_of}`
}

/** `2026-07` -> `July 2026` — the chart's window statement
 * (docs/DESIGN.md §2c.6), readable rather than machine-shaped. */
function monthLabel(month: string): string {
  return new Date(`${month}-01T00:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

function CategoryRow({
  cat,
  maxShare,
  onSelect,
}: {
  cat: MonthCategory
  maxShare: number
  onSelect?: (key: string) => void
}) {
  const fillPct = maxShare > 0 ? (cat.share_pct / maxShare) * 100 : 0
  const width = useBarFill(fillPct)
  const content = (
    <>
      <div className="flex items-center gap-2">
        <span className={`inline-block h-3 w-3 shrink-0 rounded-sm ${categoryChipClass(cat.viz_slot)}`} aria-hidden />
        <span className="flex-1 truncate text-[13px] text-ink">{cat.label}</span>
        {cat.benchmark && (
          <span
            className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] ${benchmarkPillStyle(
              cat.benchmark.band,
              cat.benchmark.severe,
            )}`}
            title={benchmarkTooltip(cat)}
          >
            {BENCHMARK_LABEL[cat.benchmark.band]}
          </span>
        )}
        <span className={`text-[13px] ${MONEY_CLASS} text-ink`}>{formatMinor(cat.spend_minor)}</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-paper-deep" aria-hidden>
        <div
          className={`h-1.5 rounded-full motion-safe:transition-[width] motion-safe:duration-500 ${categoryChipClass(cat.viz_slot)}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </>
  )

  // Clicking a category jumps to the Transactions tab pre-filtered to it
  // (docs/phases/PHASE-10-post-launch-fixes.md item 5) — only when a handler
  // is wired up; otherwise the row stays a plain (non-interactive) summary.
  if (!onSelect) {
    return <div className="space-y-1 py-2">{content}</div>
  }
  return (
    <button
      type="button"
      onClick={() => onSelect(cat.key)}
      className="block w-full space-y-1 rounded-md py-2 text-left transition hover:bg-paper-deep focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60"
      title={`View ${cat.label} transactions`}
    >
      {content}
    </button>
  )
}

/** docs/DESIGN.md §4d — category breakdown as horizontal bars (never a pie),
 * ordered by spend, each with its benchmark verdict pill (band bounds + dated
 * source in the tooltip). The methodology note is a serif footnote, always
 * visible: the bands are heuristic, never precise (docs/API.md §6b).
 * `onSelectCategory` (docs/phases/PHASE-10-post-launch-fixes.md item 5) wires
 * a category row to the Transactions tab's pre-set filter — optional so this
 * component still works standalone without the click-through. */
export function CategoryBreakdown({
  summary,
  onSelectCategory,
}: {
  summary: MonthSummary
  onSelectCategory?: (key: string) => void
}) {
  if (summary.categories.length === 0) {
    return <p className="font-serif text-[15px] text-ink-mid">No categorised spending for this month yet.</p>
  }
  const maxShare = Math.max(...summary.categories.map((c) => c.share_pct))
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">{monthLabel(summary.month)}</span>
        <span className={`text-[15px] ${MONEY_CLASS} text-ink`}>{formatMinor(summary.spend_minor)}</span>
      </div>
      <div className="divide-y divide-line">
        {summary.categories.map((c) => (
          <CategoryRow key={c.key} cat={c} maxShare={maxShare} onSelect={onSelectCategory} />
        ))}
      </div>
      <p className="font-serif text-[12px] leading-relaxed text-ink-soft">{summary.methodology_note}</p>
    </div>
  )
}
