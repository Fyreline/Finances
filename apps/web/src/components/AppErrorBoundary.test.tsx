import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

// React 19's act() checks this global before allowing synchronous act()
// calls outside a testing-library setup — harmless without it (tests still
// pass) but prints a warning on every run.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// No @testing-library/react in this repo (docs/CLAUDE.md: pure-function
// tests only, matching money.ts/shape.ts/categoryColor.ts) — this component
// is the one thing that can't be verified as a pure function, since its
// whole job is what happens when React rendering itself throws. Raw
// react-dom/client + act() covers it without adding a new dependency.

function Bomb(): never {
  throw new Error('boom')
}

let container: HTMLDivElement | null = null
let root: Root | null = null

afterEach(() => {
  if (root) act(() => root!.unmount())
  container?.remove()
  container = null
  root = null
})

function mount(children: React.ReactNode) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => root!.render(children))
  return container
}

describe('AppErrorBoundary', () => {
  it('renders children normally when nothing throws', () => {
    const el = mount(<AppErrorBoundary>{<div>fine</div>}</AppErrorBoundary>)
    expect(el.textContent).toContain('fine')
  })

  it('catches a render error and shows the calm fallback instead of going blank', () => {
    // React logs the caught error to console — expected noise here, silence it.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const el = mount(
      <AppErrorBoundary>
        <Bomb />
      </AppErrorBoundary>,
    )
    expect(el.textContent).toContain('Something needs a reload')
    expect(el.querySelector('button')?.textContent).toBe('Reload')
    spy.mockRestore()
  })
})
