import { Component, type ErrorInfo, type ReactNode } from 'react'
import { KakeiboMark } from './KakeiboMark'

/** Root-level render-error safety net. Without this, an uncaught error
 * anywhere in the tree (a component reading a field the current API
 * response doesn't have, for instance) unmounts the whole app to a blank
 * page with no clue why — exactly what happened 2026-07-11 when the API
 * LaunchAgent kept serving pre-Phase-9 responses (no `net_worth`/`wants`/
 * `gifts`) after a `git pull` had already landed the Phase-9 frontend that
 * expects them unconditionally: a component read into `undefined`, threw
 * during render, and React quietly unmounted everything. Calm tone, not a
 * guilt/alarm screen (docs/DESIGN.md §6) — this is a "something needs
 * attention" state, not a scolding, and it never touches auth state itself
 * (a render bug isn't a session problem — reload retries the same session). */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Kakeibo render error:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex min-h-full items-center justify-center bg-paper px-5 text-ink">
        <div className="w-full max-w-md text-center">
          <KakeiboMark className="mx-auto mb-4 h-9 w-9 text-clay" />
          <h1 className="font-display text-lg font-medium">Something needs a reload</h1>
          <p className="mt-2 text-sm text-ink-soft">
            A part of the page hit a snag rendering. Your data is fine — this is a display
            problem, not a data problem. Reloading usually clears it.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 rounded-md bg-ink px-4 py-2 text-sm font-medium text-paper hover:opacity-90"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
