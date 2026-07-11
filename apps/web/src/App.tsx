import { useCallback, useEffect, useRef, useState } from 'react'
import { MotionConfig } from 'motion/react'
import { bootstrap, getUser, subscribe, type AuthUser } from './auth'
import { api, type BubblesSummary, type SyncRunStatus } from './api'
import { LoginScreen } from './components/LoginScreen'
import { KakeiboMark } from './components/KakeiboMark'
import { ThemeToggle } from './components/ThemeToggle'
import { HomePage } from './components/HomePage'

/** Gates the whole app behind the household login (docs/AUTH.md).
 * `bootstrap()` tries a silent refresh from a stored refresh token on first
 * mount so a page reload doesn't force a re-login; `subscribe()` re-renders
 * this the moment auth state changes. `MotionConfig reducedMotion="user"`
 * makes every `motion.*` animation in the app (brace spring, panel open,
 * mobile sheet slide) instant for prefers-reduced-motion users in one place
 * (docs/DESIGN.md §3c "reduced motion") rather than branching per-component. */
export default function App() {
  const [user, setUser] = useState<AuthUser | null>(getUser())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const unsubscribe = subscribe(() => setUser(getUser()))
    bootstrap().finally(() => {
      setUser(getUser())
      setReady(true)
    })
    return unsubscribe
  }, [])

  if (!ready) {
    return <div className="min-h-full bg-paper" />
  }

  return (
    <MotionConfig reducedMotion="user">
      {user ? <AuthenticatedApp /> : <LoginScreen onLoggedIn={() => setUser(getUser())} />}
    </MotionConfig>
  )
}

/** `YYYY-MM-DD HH:MM:SS` UTC string (household convention, docs/ARCHITECTURE.md
 * §4) -> a relative "Xm/h/d ago" label. */
function formatAgo(dbTimestamp: string): string {
  const then = new Date(`${dbTimestamp.replace(' ', 'T')}Z`).getTime()
  const diffMinutes = Math.max(0, Math.round((Date.now() - then) / 60_000))
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const hours = Math.round(diffMinutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

/** Sync-status pill (docs/ARCHITECTURE.md §2 header spec, docs/DESIGN.md
 * §3: "kraft-warn when >24h"). As of Phase 7 it reads from the one
 * `GET /api/summary/bubbles` fetch (docs/phases/PHASE-7-dashboard.md item 6:
 * one network call renders the whole collapsed home, header pill included)
 * rather than making its own `/api/sync/status` call. */
function SyncStatusPill({ runs }: { runs: SyncRunStatus[] | null }) {
  const starling = runs?.find((r) => r.provider === 'starling') ?? null

  let label = 'connecting…'
  let dotClass = 'bg-cloud'
  let warn = false

  if (runs !== null) {
    if (!starling) {
      label = 'not synced yet'
    } else if (starling.status === 'not_configured') {
      label = 'starling not connected'
    } else if (starling.status === 'error') {
      label = 'sync error'
      dotClass = 'bg-clay'
      warn = true
    } else {
      const finishedAt = starling.finished_at ?? starling.started_at
      const hoursAgo = (Date.now() - new Date(`${finishedAt.replace(' ', 'T')}Z`).getTime()) / 3_600_000
      warn = hoursAgo > 24
      dotClass = warn ? 'bg-kraft' : 'bg-olive'
      label = `synced ${formatAgo(finishedAt)}`
    }
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px] tracking-[0.05em] ${
        warn ? 'border-kraft/60 text-ink-mid' : 'border-line-strong text-ink-soft'
      }`}
      title="Starling sync status"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} aria-hidden />
      {label}
    </span>
  )
}

function AuthenticatedApp() {
  // The one fetch that renders the whole collapsed home screen — every
  // bubble's glance plus the header pill's sync status
  // (docs/phases/PHASE-7-dashboard.md item 6: "the collapsed home should be
  // ONE fetch"). Detail panels fetch their own richer data on expand.
  //
  // Still exactly one call per refresh (Phase 7's principle intact) — but
  // "per refresh" now fires on a couple of sensible triggers beyond mount,
  // not just once ever (docs/phases/PHASE-10-post-launch-fixes.md item 2):
  // a detail panel closing (the user may have changed config, or time has
  // simply passed) and window focus (stale-while-revalidate — catches "left
  // the tab open, a sync happened"). This is what fixed the reported bug: a
  // sync that completed seconds after first load left the mount-only fetch
  // permanently stale while every detail panel (which fetches fresh on
  // open) correctly showed current data.
  const [summary, setSummary] = useState<BubblesSummary | null>(null)
  const [summaryFailed, setSummaryFailed] = useState(false)
  const inFlight = useRef(false)
  const mounted = useRef(true)

  const refetchSummary = useCallback(() => {
    if (inFlight.current) return
    inFlight.current = true
    api.bubbles().then(
      (res) => {
        if (mounted.current) {
          setSummary(res)
          setSummaryFailed(false)
        }
      },
      () => {
        if (mounted.current) setSummaryFailed(true)
      },
    ).finally(() => {
      inFlight.current = false
    })
  }, [])

  useEffect(() => {
    mounted.current = true
    refetchSummary()
    return () => {
      mounted.current = false
    }
  }, [refetchSummary])

  useEffect(() => {
    window.addEventListener('focus', refetchSummary)
    return () => window.removeEventListener('focus', refetchSummary)
  }, [refetchSummary])

  // Belt-and-braces third trigger (2026-07-11 follow-up): focus/panel-close
  // cover a lot but not "opened the site fresh and just sat on the home
  // screen without switching apps or opening a panel" — exactly how this
  // gets used from a phone home-screen icon, where a background sync can
  // complete while the user is looking straight at the (now stale) glances
  // with neither trigger ever firing. A quiet 60s poll is cheap for a
  // personal dashboard and guarantees eventual consistency regardless of
  // interaction pattern.
  useEffect(() => {
    const id = window.setInterval(refetchSummary, 60_000)
    return () => window.clearInterval(id)
  }, [refetchSummary])

  return (
    <div className="flex min-h-full flex-col bg-paper text-ink">
      <header className="sticky top-0 z-20 border-b border-line bg-paper/95">
        <div className="mx-auto flex max-w-[72rem] items-center justify-between gap-3 px-5 py-3">
          <div className="flex shrink-0 items-baseline gap-2.5 whitespace-nowrap">
            {/* The wordmark's hanko square is the one deliberate crimson on a
                default dashboard (docs/DESIGN.md §7); 家計簿 sits beside it in
                ink-soft 12px per the §3 header spec — dropped below 400px
                (narrow mobile) so the sync pill never wraps the wordmark. */}
            <KakeiboMark className="h-7 w-7 shrink-0 self-center text-clay" />
            <span className="font-display text-lg font-medium tracking-[-0.005em]">Kakeibo</span>
            <span className="hidden font-mono text-[12px] text-ink-soft min-[400px]:inline">家計簿</span>
          </div>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <SyncStatusPill runs={summaryFailed ? [] : (summary?.sync.runs ?? null)} />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="flex-1">
        <HomePage summary={summary} onPanelClose={refetchSummary} />
      </main>
    </div>
  )
}
