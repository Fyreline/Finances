/** Shared shell for every detail panel this phase — "Detail panels are
 * placeholder frames this phase; the interaction ships now so every later
 * phase drops content into a working pattern" (docs/phases/PHASE-1-scaffold.md
 * item 4). Calm, honest, no fake numbers (docs/PLAN.md §6). */
export function PlaceholderDetail({ title, body, phase }: { title: string; body: string; phase: string }) {
  return (
    <div className="max-w-2xl space-y-2">
      <h3 className="font-display text-lg font-medium text-ink">{title}</h3>
      <p className="font-serif text-base text-ink-mid">{body}</p>
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">{phase}</p>
    </div>
  )
}
