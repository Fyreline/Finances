import { useCallback, useEffect, useState } from 'react'
import {
  api,
  ApiError,
  type Category,
  type TransactionFilters,
  type TransactionItem,
  type TransactionPatch,
} from '../api'
import { MONEY_CLASS, formatMinorSigned } from '../money'
import { categoryChipClass } from '../categoryColor'

/** docs/DESIGN.md §4e — desktop table / mobile card-rows. Columns: date
 * (mono 11px), counterparty (+ reference beneath), category chip (click →
 * recategorise popover, writes PATCH, `manual` badge), amount right-aligned
 * mono (income `+` in gain, spending plain ink). Unsettled rows at 40%
 * opacity with a `pending` pill; rental-flag toggle in the row's overflow
 * menu. 50/page, mono pagination. */

function monthHeading(localDate: string): string {
  const d = new Date(`${localDate}T00:00:00`)
  return d.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

function CategoryPopover({
  categories,
  onSelect,
  onClose,
}: {
  categories: Category[]
  onSelect: (categoryId: number) => void
  onClose: () => void
}) {
  return (
    <>
      <div className="fixed inset-0 z-10" onClick={onClose} aria-hidden />
      <div
        role="menu"
        className="absolute left-0 top-full z-20 mt-1 max-h-64 w-56 overflow-y-auto rounded-md border border-line-strong bg-paper p-1 shadow-float"
      >
        {categories.map((c) => (
          <button
            key={c.id}
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left font-sans text-sm text-ink hover:bg-paper-mid"
            onClick={() => {
              onSelect(c.id)
              onClose()
            }}
          >
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${categoryChipClass(c.viz_slot)}`} aria-hidden />
            {c.label}
          </button>
        ))}
      </div>
    </>
  )
}

function TransactionRow({
  txn,
  categories,
  onPatched,
}: {
  txn: TransactionItem
  categories: Category[]
  onPatched: (updated: TransactionItem) => void
}) {
  const [popoverOpen, setPopoverOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const patch = useCallback(
    async (body: TransactionPatch) => {
      setBusy(true)
      setError(null)
      try {
        const { transaction } = await api.patchTransaction(txn.id, body)
        onPatched(transaction)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not save that change')
      } finally {
        setBusy(false)
      }
    },
    [txn.id, onPatched],
  )

  const isIncome = txn.amount_minor > 0
  const category = txn.category ? categories.find((c) => c.id === txn.category!.id) : undefined

  return (
    <div
      className={`grid grid-cols-[52px_1fr_auto_auto] items-center gap-3 border-b border-line px-3 py-2.5 min-h-[44px] ${
        txn.settled ? '' : 'opacity-40'
      }`}
    >
      <span className="font-mono text-[11px] text-ink-soft">{txn.local_date.slice(5)}</span>

      <div className="min-w-0">
        <div className="truncate text-sm text-ink">{txn.counterparty ?? '—'}</div>
        {txn.reference && <div className="truncate font-mono text-[11px] text-ink-soft">{txn.reference}</div>}
      </div>

      <div className="relative flex items-center gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => setPopoverOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={popoverOpen}
          className="flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 font-mono text-[11px] text-ink-mid transition hover:border-line-strong disabled:opacity-50"
        >
          <span className={`h-2 w-2 rounded-full ${categoryChipClass(category?.viz_slot ?? null)}`} aria-hidden />
          {txn.category?.label ?? 'Uncategorised'}
        </button>
        {txn.category_source === 'manual' && (
          <span className="font-mono text-[11px] text-ink-soft" title="Manually categorised">
            ⌁
          </span>
        )}
        {!txn.settled && (
          <span className="rounded-full bg-oat px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.06em] text-ink-mid">
            pending
          </span>
        )}
        {popoverOpen && (
          <CategoryPopover
            categories={categories}
            onClose={() => setPopoverOpen(false)}
            onSelect={(categoryId) => void patch({ category_id: categoryId })}
          />
        )}
      </div>

      <div className="relative flex items-center gap-2">
        <span className={`${MONEY_CLASS} text-sm ${isIncome ? 'text-gain' : 'text-ink'}`}>
          {formatMinorSigned(txn.amount_minor)}
        </span>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="Row actions"
          aria-haspopup="menu"
          className="rounded px-1 text-ink-soft hover:text-ink"
        >
          ⋯
        </button>
        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} aria-hidden />
            <div
              role="menu"
              className="absolute right-0 top-full z-20 mt-1 w-44 rounded-md border border-line-strong bg-paper p-1 shadow-float"
            >
              <button
                type="button"
                role="menuitem"
                disabled={busy}
                className="w-full rounded-sm px-2 py-1.5 text-left text-sm text-ink hover:bg-paper-mid disabled:opacity-50"
                onClick={() => {
                  setMenuOpen(false)
                  void patch({ is_rental: !txn.is_rental })
                }}
              >
                {txn.is_rental ? 'Unflag as rental' : 'Flag as rental'}
              </button>
            </div>
          </>
        )}
      </div>

      {error && <div className="col-span-4 font-mono text-[11px] text-fig">{error}</div>}
    </div>
  )
}

interface TransactionTableProps {
  /** Pre-set filters (e.g. a category clicked in the Breakdown tab, Phase 4)
   * — the table still owns its own search box and pagination on top. */
  initialFilters?: TransactionFilters
}

export function TransactionTable({ initialFilters }: TransactionTableProps) {
  const [categories, setCategories] = useState<Category[]>([])
  const [items, setItems] = useState<TransactionItem[]>([])
  const [total, setTotal] = useState(0)
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(initialFilters?.page ?? 1)
  const [month, setMonth] = useState(initialFilters?.month ?? '')
  const [category, setCategory] = useState(initialFilters?.category ?? '')
  const [q, setQ] = useState(initialFilters?.q ?? '')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    api.categories().then(
      (res) => setCategories(res.categories),
      () => setCategories([]),
    )
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    api.transactions({ month: month || undefined, category: category || undefined, q: q || undefined, page }).then(
      (res) => {
        setItems(res.items)
        setTotal(res.total)
        setPageSize(res.page_size)
        setLoading(false)
      },
      (err) => {
        setLoadError(err instanceof ApiError ? err.message : 'Could not load transactions')
        setLoading(false)
      },
    )
  }, [month, category, q, page])

  useEffect(() => {
    load()
  }, [load])

  const handlePatched = useCallback((updated: TransactionItem) => {
    setItems((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
  }, [])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  let lastHeading = ''

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="month"
          value={month}
          onChange={(e) => {
            setMonth(e.target.value)
            setPage(1)
          }}
          className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-[12px] text-ink"
          aria-label="Filter by month"
        />
        <select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value)
            setPage(1)
          }}
          className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-[12px] text-ink"
          aria-label="Filter by category"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.id} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
        <input
          type="search"
          value={q}
          placeholder="Search counterparty or reference"
          onChange={(e) => {
            setQ(e.target.value)
            setPage(1)
          }}
          className="min-w-48 flex-1 rounded-md border border-line bg-paper px-2 py-1 text-sm text-ink placeholder:text-ink-soft"
          aria-label="Search transactions"
        />
      </div>

      {loadError && <p className="font-serif text-sm text-clay">{loadError}</p>}

      {!loadError && !loading && items.length === 0 && (
        <p className="font-serif text-sm text-ink-mid">
          No transactions yet — connect Starling and run a sync to begin.
        </p>
      )}

      {items.length > 0 && (
        <div className="overflow-hidden rounded-md border border-line">
          {items.map((txn) => {
            const heading = monthHeading(txn.local_date)
            const showHeading = heading !== lastHeading
            lastHeading = heading
            return (
              <div key={txn.id}>
                {showHeading && (
                  <div className="sticky top-0 z-10 border-b border-line bg-paper-mid px-3 py-1 font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
                    {heading}
                  </div>
                )}
                <TransactionRow txn={txn} categories={categories} onPatched={handlePatched} />
              </div>
            )
          })}
        </div>
      )}

      {total > 0 && (
        <div className="flex items-center justify-between font-mono text-[11px] text-ink-soft">
          <span>{total} transactions</span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="disabled:opacity-30"
            >
              ← prev
            </button>
            <span>
              page {page} of {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="disabled:opacity-30"
            >
              next →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
