/** Kakeibo's wordmark glyph — a gamaguchi coin purse (clasp-frame dome, two
 * clasp balls, fat pouch) carrying the household cat mark where the coins
 * live: the same object-plus-cat-badge idiom as Mishka Hub's film camera and
 * Michi's torii, applied to money. Line-art outline (Mishka technique) so
 * the solid cat badge stays legible inside the open pouch. Explicit
 * width/height are passed through rather than relying on CSS sizing — a
 * nested `<svg>` ignores class-based sizing (household gotcha, see Michi's
 * CLAUDE.md).
 *
 * The purse draws in `currentColor` (docs/phases/PHASE-7-dashboard.md item 5)
 * so callers pick its ink with a text class — `text-clay` in the header —
 * and it re-inks itself with the theme; the cat's eyes and mouth are knocked
 * out in `paper` so they read as the unstamped ground. The favicon and
 * home-screen icon (`public/kakeibo-icon.svg`, `public/apple-touch-icon.png`)
 * are this same mark flat-exported with the light-theme clay/paper values
 * (a favicon can't read CSS variables) — keep the geometry in step. */
export function KakeiboMark({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      {/* +0.5 y-nudge centres the painted extents in the viewBox — keep in
          step with public/kakeibo-icon.svg */}
      <g transform="translate(0 0.5)">
        <circle cx="14.2" cy="4.8" r="1.7" fill="currentColor" />
        <circle cx="17.8" cy="4.8" r="1.7" fill="currentColor" />
        <path d="M 6,14 A 10,8 0 0 1 26,14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path d="M 6,14 L 26,14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path d="M 6,14 C 4.2,20.5 6.8,27 16,27 C 25.2,27 27.8,20.5 26,14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <g transform="translate(10.08,15.41) scale(0.37)">
          <path
            d="M4,9 L2,1.5 L10,7.5 Q16,4 22,7.5 L30,1.5 L28,9 Q30.5,14.5 28,20 Q24.5,26 16,26 Q7.5,26 4,20 Q1.5,14.5 4,9 Z"
            fill="currentColor"
          />
          <circle cx="12" cy="16.5" r="1.6" fill="var(--color-paper)" />
          <circle cx="20" cy="16.5" r="1.6" fill="var(--color-paper)" />
          <path d="M15,20 L17,20 L16,21.3 Z" fill="var(--color-paper)" />
        </g>
      </g>
    </svg>
  )
}
