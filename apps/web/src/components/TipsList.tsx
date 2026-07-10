import { useEffect, useState } from 'react'
import { api, type Tip } from '../api'

const SEVERITY_STYLE: Record<string, string> = {
  // Calm tones only — no alarm, no crimson banner (docs/DESIGN.md §6).
  info: 'border-line bg-paper',
  worth_a_look: 'border-kraft/40 bg-oat/40',
}

/** Tips tab (docs/API.md §6c, DESIGN §6): advisory cards with a dismiss
 * action. Every sentence is server-side template copy — this component never
 * writes advice, it only renders and dismisses. */
export function TipsList({ period }: { period: string }) {
  const [tips, setTips] = useState<Tip[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .tips(period)
      .then((r) => !cancelled && setTips(r.tips))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Couldn't load tips"))
    return () => {
      cancelled = true
    }
  }, [period])

  if (error) return <p className="text-[13px] text-ink-mid">{error}</p>
  if (!tips) return <p className="font-mono text-[11px] text-ink-soft">Loading…</p>
  if (tips.length === 0) {
    return <p className="font-serif text-[15px] text-ink-mid">Nothing worth flagging this month — all steady.</p>
  }

  async function dismiss(id: number) {
    setTips((prev) => (prev ? prev.filter((t) => t.id !== id) : prev))
    try {
      await api.dismissTip(id)
    } catch {
      /* optimistic; a reload would restore it if the call really failed */
    }
  }

  return (
    <ul className="space-y-3">
      {tips.map((tip) => (
        <li key={tip.id} className={`rounded-lg border p-4 ${SEVERITY_STYLE[tip.severity] ?? SEVERITY_STYLE.info}`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[14px] font-medium text-ink">{tip.title}</p>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-mid">{tip.body}</p>
            </div>
            <button
              type="button"
              onClick={() => dismiss(tip.id)}
              className="shrink-0 font-mono text-[11px] uppercase tracking-[0.06em] text-ink-soft hover:text-ink-mid"
              aria-label={`Dismiss: ${tip.title}`}
            >
              Dismiss
            </button>
          </div>
        </li>
      ))}
    </ul>
  )
}
