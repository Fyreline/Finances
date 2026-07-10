/** Kakeibo's wordmark glyph — a small hanko (seal-stamp) square carrying 家
 * (house/household), echoing the crimson ink-stamp motif the household's
 * other marks draw from (MichiMark, Mishka's cat mark). Deliberately plain:
 * Kakeibo is "a desk", not a poster (docs/DESIGN.md intro). Explicit
 * width/height are passed through rather than relying on CSS sizing — a
 * nested `<svg>` ignores class-based sizing (household gotcha, see Michi's
 * CLAUDE.md).
 *
 * The seal draws in `currentColor` (docs/phases/PHASE-7-dashboard.md item 5)
 * so callers pick its ink with a text class — `text-clay` in the header —
 * and it re-inks itself with the theme; the 家 glyph is knocked out in
 * `paper` so it reads as the unstamped ground. The favicon in `index.html`
 * is this same mark flat-exported with the light-theme clay/paper values
 * (a favicon can't read CSS variables). */
export function KakeiboMark({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      <rect x="2" y="2" width="28" height="28" rx="6" fill="currentColor" />
      <text
        x="16"
        y="22.5"
        textAnchor="middle"
        fontSize="17"
        fontFamily="var(--font-sans)"
        fill="var(--color-paper)"
      >
        家
      </text>
    </svg>
  )
}
