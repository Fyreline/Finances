import { forwardRef, type ReactNode } from 'react'

export interface BubbleProps {
  title: string
  /** Setup-state serif line(s) — every bubble falls back to this when its
   * integration/goal is `not_configured` (docs/DESIGN.md §3b: "never shows
   * fake numbers"). */
  lines: string[]
  hero?: boolean
  active: boolean
  onClick: () => void
  /** Richer glance content once real data exists (a hero figure, a
   * progress bar, a sparkline — docs/DESIGN.md §3d "one hero figure plus at
   * most three supporting elements"). Rendered *instead of* `lines` when
   * provided — a bubble is either in its calm setup state or showing real
   * numbers, never both at once. */
  children?: ReactNode
}

/** Collapsed tile shell (docs/DESIGN.md §3a): rounded-square card, not a
 * literal circle — hairline border, hover lift, press-scale. `active`
 * marks the bubble whose detail panel is currently open (border-clay/60,
 * docs/DESIGN.md §3c). */
export const Bubble = forwardRef<HTMLButtonElement, BubbleProps>(function Bubble(
  { title, lines, hero, active, onClick, children },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      aria-expanded={active}
      className={`flex min-h-32 flex-col items-start gap-2 rounded-lg border bg-paper-mid p-5 text-left transition hover:border-line-strong hover:-translate-y-px active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-clay/60 motion-reduce:transition-none motion-reduce:hover:translate-y-0 ${
        active ? 'border-clay/60' : 'border-line'
      } ${hero ? 'col-span-full' : ''}`}
    >
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">{title}</span>
      {children ?? (
        lines.map((line) => (
          <p key={line} className="font-serif text-sm text-ink-mid">
            {line}
          </p>
        ))
      )}
    </button>
  )
})
