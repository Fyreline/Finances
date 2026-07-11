import { useEffect, useState } from 'react'
import { api, type FinancialConfig, type SafeToSpend } from '../../api'
import { safeToSpendSegments, WaterfallStrip } from '../../charts/WaterfallStrip'
import { useSafeToSpend } from '../../hooks/useSafeToSpend'
import { formatMinor, MONEY_CLASS, poundsToMinor } from '../../money'

function periodLabel(start: string | null, end: string | null): string {
  if (!start || !end) return ''
  const fmt = (d: string) =>
    new Date(`${d}T00:00:00`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }).toUpperCase()
  return `${fmt(start)} – ${fmt(end)}`
}

/** One line of the §6a formula: label + signed amount. `op` renders the
 * running-total operator so the deductions read as a waterfall. Ordinary
 * deductions print in ink — money leaving is normal life, not an error; only
 * a genuine threshold (a negative running total on a `strong` row) is crimson
 * (docs/DESIGN.md §6). */
function FormulaRow({ label, minor, op, strong }: { label: string; minor: number; op?: string; strong?: boolean }) {
  const crimson = strong && minor < 0
  return (
    <div className={`flex items-baseline justify-between py-1 ${strong ? 'border-t border-line font-medium' : ''}`}>
      <span className="text-[13px] text-ink-mid">
        {op && <span className="mr-1 text-ink-soft">{op}</span>}
        {label}
      </span>
      <span className={`text-[13px] ${MONEY_CLASS} ${crimson ? 'text-over' : 'text-ink'}`}>{formatMinor(minor)}</span>
    </div>
  )
}

/** Phase 11: when payday and/or income were inferred from transaction history
 * rather than typed in, say so plainly and offer an obvious override — a
 * detected figure is a calm, labelled guess, never presented as fact
 * (docs/phases/PHASE-11-payday-autodetect.md §4). */
function DetectedBanner({ data, onOverride }: { data: SafeToSpend; onOverride: () => void }) {
  const paydayDetected = data.payday_source === 'detected'
  const incomeDetected = data.net_income_source === 'detected'
  if (!paydayDetected && !incomeDetected) return null

  const d = data.detected_income
  const what = paydayDetected && incomeDetected ? 'Payday and take-home pay are' : paydayDetected ? 'Payday is' : 'Take-home pay is'
  const gap = d?.median_gap_days ? `about every ${d.median_gap_days} days` : 'on a regular cadence'
  const amount = d ? formatMinor(d.typical_amount_minor) : ''

  return (
    <div className="space-y-2 rounded-lg border border-line bg-oat/40 p-3">
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Worked out from your history</p>
      <p className="text-[13px] text-ink-mid">
        {what} worked out from a recurring payment{d ? <> from <span className="text-ink">{d.label}</span></> : null}
        {d ? <> averaging {amount}, arriving {gap}</> : null}. These are informed guesses, not something you told
        Kakeibo — override below if they are wrong.
      </p>
      <button
        type="button"
        onClick={onOverride}
        className="font-mono text-[11px] uppercase tracking-[0.08em] text-clay-deep underline-offset-2 hover:underline"
      >
        Set these myself
      </button>
    </div>
  )
}

function ConfigForm({ onSaved }: { onSaved: () => void }) {
  const [config, setConfig] = useState<FinancialConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.financialConfig().then((r) => setConfig(r.financial_config))
  }, [])

  if (!config) return <p className="font-mono text-[11px] text-ink-soft">Loading settings…</p>

  const toPounds = (minor: number | null) => (minor === null ? '' : (minor / 100).toString())
  const setField = (patch: Partial<FinancialConfig>) => setConfig({ ...config, ...patch })

  async function save() {
    if (!config) return
    setSaving(true)
    setErr(null)
    try {
      await api.putFinancialConfig({
        payday_day: config.payday_day,
        net_monthly_income_minor: config.net_monthly_income_minor,
        flat_share_minor: config.flat_share_minor,
        buffer_minor: config.buffer_minor,
        tax_setaside_mode: config.tax_setaside_mode,
      })
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  const field = 'w-28 rounded-md border border-line bg-paper px-2 py-1 text-right font-mono text-[13px] text-ink'
  const label = 'flex items-center justify-between gap-3 text-[13px] text-ink-mid'

  return (
    <div className="space-y-3 rounded-lg border border-line bg-paper p-4">
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">Your figures</p>
      <label className={label}>
        Payday (day of month)
        <input
          type="number"
          min={1}
          max={31}
          className={field}
          value={config.payday_day ?? ''}
          onChange={(e) => setField({ payday_day: e.target.value ? Number(e.target.value) : null })}
        />
      </label>
      <label className={label}>
        Take-home pay (£/month)
        <input
          type="number"
          className={field}
          value={toPounds(config.net_monthly_income_minor)}
          onChange={(e) =>
            setField({ net_monthly_income_minor: e.target.value ? poundsToMinor(Number(e.target.value)) : null })
          }
        />
      </label>
      <label className={label}>
        Flat share (£/month)
        <input
          type="number"
          className={field}
          value={toPounds(config.flat_share_minor)}
          onChange={(e) => setField({ flat_share_minor: e.target.value ? poundsToMinor(Number(e.target.value)) : null })}
        />
      </label>
      <label className={label}>
        Buffer (£/month)
        <input
          type="number"
          className={field}
          value={toPounds(config.buffer_minor)}
          onChange={(e) => setField({ buffer_minor: e.target.value ? poundsToMinor(Number(e.target.value)) : 0 })}
        />
      </label>
      <label className={label}>
        Tax set-aside
        <select
          className={field}
          value={config.tax_setaside_mode}
          onChange={(e) => setField({ tax_setaside_mode: e.target.value as FinancialConfig['tax_setaside_mode'] })}
        >
          <option value="auto">Auto</option>
          <option value="fixed">Fixed</option>
          <option value="off">Off</option>
        </select>
      </label>
      {err && <p className="text-[12px] text-over">{err}</p>}
      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="rounded-md border border-clay/60 bg-clay/10 px-3 py-1.5 text-[13px] text-clay-deep transition hover:bg-clay/20 disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  )
}

export function SafeToSpendDetail() {
  const { data, loading, error, reload } = useSafeToSpend()
  const [showSettings, setShowSettings] = useState(false)

  // A fetch failure must surface as an error, not read as "still loading"
  // forever — the exact bug Phase 9's real-credential testing found here
  // (docs/phases/PHASE-10-post-launch-fixes.md item 3): `loading` flips
  // false and `data` stays null on error, so this branch must come first.
  if (error) {
    return (
      <p className="text-[13px] text-ink-mid">
        {error}{' '}
        <button type="button" onClick={reload} className="underline">
          retry
        </button>
      </p>
    )
  }
  if (loading || !data) return <p className="font-mono text-[11px] text-ink-soft">Loading…</p>

  const onSaved = () => {
    setShowSettings(false)
    reload()
  }

  if (data.safe_to_spend_minor === null) {
    return (
      <div className="space-y-4">
        <p className="font-serif text-[15px] text-ink-mid">
          Tell Kakeibo about payday and take-home pay to unlock this.
        </p>
        <ConfigForm onSaved={onSaved} />
      </div>
    )
  }

  const safe = data.safe_to_spend_minor
  return (
    <div className="space-y-5">
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
          SAFE TO SPEND · {periodLabel(data.period.start, data.period.end)}
        </p>
        <p className={`text-[38px] leading-tight ${MONEY_CLASS} ${safe < 0 ? 'text-over' : 'text-ink'}`}>
          {formatMinor(safe)}
        </p>
        <p className="text-[13px] text-ink-soft">
          {formatMinor(data.per_day_remaining_minor ?? 0)}/day for the next {data.days_left ?? 0} days
        </p>
      </div>

      <DetectedBanner data={data} onOverride={() => setShowSettings(true)} />

      <WaterfallStrip segments={safeToSpendSegments(data)} totalMinor={data.income_minor} />

      <div className="rounded-lg border border-line bg-paper p-4">
        <FormulaRow label="Take-home pay" minor={data.net_income_minor} />
        {data.rental_income_minor > 0 && <FormulaRow label="Rental income" minor={data.rental_income_minor} op="+" />}
        <FormulaRow label="Income" minor={data.income_minor} strong />
        <FormulaRow label="Committed obligations" minor={-data.committed_minor} op="−" />
        <FormulaRow label="Goal contributions" minor={-data.goal_set_aside_minor} op="−" />
        <FormulaRow label="Tax set-aside" minor={-data.tax_set_aside_minor} op="−" />
        <FormulaRow label="Buffer" minor={-data.buffer_minor} op="−" />
        <FormulaRow label="Safe to spend" minor={safe} strong />
        <FormulaRow label="Spent so far" minor={-data.spent_so_far_minor} op="−" />
        <FormulaRow label="Remaining" minor={data.remaining_minor ?? 0} strong />
      </div>

      <button
        type="button"
        onClick={() => setShowSettings((s) => !s)}
        className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft underline-offset-2 hover:text-ink-mid hover:underline"
      >
        {showSettings ? 'Hide settings' : 'Payday, income, buffer'}
      </button>
      {showSettings && <ConfigForm onSaved={onSaved} />}
    </div>
  )
}
