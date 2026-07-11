import { useEffect, useState } from 'react'
import { api, type NetWorth } from '../../api'
import { TrendLine } from '../../charts/TrendLine'
import { EMERGENCY_FUND_LABEL, EMERGENCY_FUND_STYLE } from '../../charts/verdict'
import { formatMinor, formatMinorWhole, MONEY_CLASS } from '../../money'

/** S2 (docs/PLAN.md §4 S2, docs/phases/PHASE-9-personal-goals.md §2) — a
 * quiet section inside the Net Worth detail rather than its own bubble, per
 * the phase's judgement call (they share the same accessible-cash data,
 * documented in docs/DESIGN.md §3b row 8). Every band, including the
 * lowest, renders calm (kraft, never crimson) — a low reading can be a
 * deliberate trade-off while saving toward another goal, not a failing. */
function EmergencyFundSection({ data }: { data: NetWorth['emergency_fund'] }) {
  return (
    <div className="space-y-1.5 border-t border-line pt-4">
      <h4 className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Emergency fund</h4>
      <div className="flex flex-wrap items-center gap-2">
        {data.months_of_cover !== null && (
          <span className={`text-lg ${MONEY_CLASS} text-ink`}>{data.months_of_cover} months</span>
        )}
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] ${EMERGENCY_FUND_STYLE[data.verdict]}`}
        >
          {EMERGENCY_FUND_LABEL[data.verdict]}
        </span>
      </div>
      <p className="font-serif text-sm text-ink-mid">{data.copy}</p>
    </div>
  )
}

/** S4 (docs/PLAN.md §4 S4, docs/phases/PHASE-9-personal-goals.md §3) — a
 * quiet card, not its own bubble (same judgement call as S2). Tri-state
 * pension answer renders "not sure yet" honestly, never a false "no"
 * (docs/PRIVATE.md). The FTE-runway goal, once a conversion date is set,
 * surfaces via the same goal shape `GET /api/goals` returns — its target
 * amount is set later via the ordinary goal edit, never invented here. */
function ContractorGapSection({ data }: { data: NetWorth['contractor_gap'] }) {
  const pensionLine =
    data.pension_contributing === null
      ? 'Pension: not sure yet — check with your consultancy.'
      : data.pension_contributing
        ? 'Pension: contributions are going in.'
        : 'Pension: nothing currently going in.'

  return (
    <div className="space-y-1.5 border-t border-line pt-4">
      <h4 className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Contractor gap</h4>
      <p className="font-serif text-sm text-ink-mid">{pensionLine}</p>
      {data.fte_conversion_target_date === null ? (
        <p className="font-serif text-sm text-ink-mid">
          No FTE conversion date set yet — add one in financial config to track a runway buffer.
        </p>
      ) : (
        <FteRunwayLine goal={data.fte_runway_goal} targetDate={data.fte_conversion_target_date} />
      )}
    </div>
  )
}

function FteRunwayLine({ goal, targetDate }: { goal: NetWorth['contractor_gap']['fte_runway_goal']; targetDate: string }) {
  if (goal === null || goal.target_minor === null) {
    return (
      <p className="font-serif text-sm text-ink-mid">
        Conversion target {targetDate} — set a buffer target on the fte_runway goal to see a progress bar here.
      </p>
    )
  }
  return (
    <p className="font-serif text-sm text-ink-mid">
      Conversion target {targetDate}: {formatMinor(goal.current_minor)} of {formatMinorWhole(goal.target_minor)} saved.
    </p>
  )
}

function AccountBreakdown({ data }: { data: NetWorth }) {
  if (data.by_account.length === 0) {
    return <p className="font-serif text-sm text-ink-mid">No accounts included in net worth yet.</p>
  }
  return (
    <div className="divide-y divide-line">
      {data.by_account.map((account) => (
        <div key={account.account_id} className="flex items-baseline justify-between py-2">
          <span className="text-[14px] text-ink">{account.name}</span>
          <span className={`text-[14px] ${MONEY_CLASS} text-ink`}>{formatMinor(account.balance_minor)}</span>
        </div>
      ))}
    </div>
  )
}

/** Net Worth detail (docs/DESIGN.md §3b row 8): trend chart + per-account
 * breakdown, plus the S2/S4 sections this phase folded in rather than
 * adding two more bubbles (docs/phases/PHASE-9-personal-goals.md §2/§3). */
export function NetWorthDetail() {
  const [data, setData] = useState<NetWorth | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .networth()
      .then((res) => !cancelled && setData(res))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Couldn't load"))
    return () => {
      cancelled = true
    }
  }, [])

  if (error) return <p className="text-[13px] text-ink-mid">{error}</p>
  if (!data) return <p className="font-mono text-[11px] text-ink-soft">Loading…</p>

  return (
    <div className="max-w-2xl space-y-4">
      <h3 className="font-display text-lg font-medium text-ink">Net worth</h3>
      <div className={`text-2xl ${MONEY_CLASS} text-ink`}>{formatMinorWhole(data.total_minor)}</div>
      {data.series.length > 0 ? (
        <>
          <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">last 90 days</p>
          <TrendLine series={data.series.map((p) => ({ date: p.date, value_minor: p.total_minor }))} />
        </>
      ) : (
        <p className="font-serif text-sm text-ink-mid">Not enough history yet for a trend chart.</p>
      )}
      <AccountBreakdown data={data} />
      <EmergencyFundSection data={data.emergency_fund} />
      <ContractorGapSection data={data.contractor_gap} />
    </div>
  )
}
