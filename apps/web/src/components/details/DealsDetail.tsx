import { useEffect, useState } from 'react'
import { api, type DealsResponse, type SavingsDeal } from '../../api'
import { useGoals } from '../../hooks/useGoals'
import { formatMinor, MONEY_CLASS } from '../../money'
import { PlaceholderDetail } from './PlaceholderDetail'

function checkedDateLabel(runAt: string): string {
  return new Date(runAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

const ACCESS_LABEL: Record<SavingsDeal['access'], string> = {
  easy: 'easy access',
  notice: 'notice account',
  limited_withdrawals: 'limited withdrawals',
}

/** `your £X here ≈ £Y/year` — docs/DESIGN.md §4h: "simple AER × balance,
 * labelled 'rough'". This derives a NEW money figure from a percentage, so —
 * same convention as money.ts's `poundsToMinor` — the float touches money
 * exactly once, immediately rounded to the nearest penny. Never stored,
 * display-only. */
function roughAnnualIncomeMinor(balanceMinor: number, aerPct: number): number {
  return Math.round(balanceMinor * (aerPct / 100))
}

function DealCard({ deal, balanceMinor }: { deal: SavingsDeal; balanceMinor: number | null }) {
  return (
    <div className="rounded-lg border border-line bg-paper p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="font-display text-base font-medium text-ink">{deal.provider}</div>
          <div className="font-serif text-sm text-ink-mid">{deal.product}</div>
        </div>
        <div className={`text-2xl ${MONEY_CLASS} text-ink`}>{deal.aer_pct.toFixed(2)}% AER</div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-oat px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-mid">
          {ACCESS_LABEL[deal.access]}
        </span>
        {deal.fscs && (
          <span className="rounded-full bg-olive/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-olive">
            FSCS
          </span>
        )}
        {deal.is_isa && (
          <span className="rounded-full bg-setaside/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-mid">
            ISA
          </span>
        )}
        {deal.min_deposit_minor !== null && deal.min_deposit_minor > 0 && (
          <span className="font-mono text-[11px] text-ink-soft">min {formatMinor(deal.min_deposit_minor)}</span>
        )}
      </div>
      {deal.notes && <p className="mt-2 font-serif text-sm text-ink-mid">{deal.notes}</p>}
      {balanceMinor !== null && balanceMinor > 0 && (
        <p className={`mt-2 font-mono text-[11px] ${MONEY_CLASS} text-ink-soft`}>
          your {formatMinor(balanceMinor)} here ≈ {formatMinor(roughAnnualIncomeMinor(balanceMinor, deal.aer_pct))}/year
          (rough)
        </p>
      )}
      <a
        href={deal.source_url}
        target="_blank"
        rel="noreferrer"
        className="mt-3 flex flex-wrap items-center gap-2 font-mono text-[11px] text-ink-soft underline decoration-line-strong underline-offset-2 hover:text-ink"
      >
        source
      </a>
    </div>
  )
}

/** DealsPage (docs/DESIGN.md §4h, docs/API.md §4). Never a live feed —
 * every surface carries the research run's as-of date, and a run older than
 * 35 days (server-computed, docs/engines/deals.py `is_stale`) banners the
 * whole page. `data/deals/` is seeded with one clearly-synthetic placeholder
 * file at first boot (docs/app/seed_deals.py) purely so this renders
 * end-to-end before the first real research pass
 * (docs/DEPLOYMENT.md §4d) — that placeholder is unmistakably labelled, never
 * presented as a real rate. */
export function DealsDetail() {
  const [data, setData] = useState<DealsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { goalsByKey } = useGoals()
  const balanceMinor = goalsByKey.t212_rebuild?.current_minor ?? null

  useEffect(() => {
    let cancelled = false
    api
      .deals()
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load deals")
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return <p className="font-serif text-sm text-ink-mid">Couldn't load savings deals ({error}).</p>
  }
  if (!data) {
    return <p className="font-serif text-sm text-ink-mid">Loading…</p>
  }
  if (!data.run || data.deals.length === 0) {
    return (
      <PlaceholderDetail
        title="Savings deals"
        body="No research run yet — a scheduled research pass will write dated, source-cited easy-access savings rates here (docs/DEPLOYMENT.md §4d)."
        phase="docs/API.md §4"
      />
    )
  }

  return (
    <div className="max-w-2xl space-y-4">
      <h3 className="font-display text-lg font-medium text-ink">Savings deals</h3>
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
        checked {checkedDateLabel(data.run.run_at)} · not a live feed, periodic research only
      </p>
      {data.stale && (
        <div className="rounded-md bg-oat p-3 text-ink-mid">
          <p className="font-serif text-sm text-ink">
            These rates were researched on {checkedDateLabel(data.run.run_at)} and may have changed.
          </p>
        </div>
      )}
      <div className="space-y-3">
        {data.deals.map((deal) => (
          <DealCard key={deal.id} deal={deal} balanceMinor={balanceMinor} />
        ))}
      </div>
      <div className="space-y-1 border-t border-line pt-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">sources</p>
        {data.run.sources.map((source) => (
          <a
            key={source.url}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="block font-mono text-[11px] text-ink-soft underline decoration-line-strong underline-offset-2 hover:text-ink"
          >
            {source.url}
          </a>
        ))}
      </div>
    </div>
  )
}
