#!/usr/bin/env node
// Rasterises the KakeiboMark hanko (seal + 家) into apple-touch-icon.png. Run
// manually, only when the mark changes:
//   node scripts/generate-apple-touch-icon.mjs
// Dev-only (sharp is a devDependency, Japan_website precedent) — never
// imported by app code, never shipped.
//
// iOS 26's home-screen treatment (the layered "liquid glass" look) needs a
// full-bleed OPAQUE square: no transparency, no baked rounded corners — the
// OS applies its own mask. The old icon WAS the bare rounded seal with
// transparent corners, so iOS rendered it as a flat tile. Instead the seal
// now sits stamped at ~70% on a paper ground, the same framing as Michi's
// and Japan's icons (HOUSEHOLD-DESIGN.md §8).
//
// Hex exception: icon scripts can't read CSS custom properties — values must
// match theme.css's light `clay`/`paper` exactly (the documented favicon
// exception; same pair as index.html's data-URI favicon).
const CLAY = '#c33c54'
const PAPER = '#f7fbfa'

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import sharp from 'sharp'

const __dirname = dirname(fileURLToPath(import.meta.url))
const publicDir = join(__dirname, '..', 'public')

// Same proportions as KakeiboMark.tsx's 32x32 mark (rect 28 @ rx 6, 家 at
// font-size 17, baseline 22.5), scaled so the seal is 126px (70%) of the
// 180px canvas: rx 27, font 76.5, baseline offset 0.732 of the seal.
const SEAL = 126
const PAD = (180 - SEAL) / 2
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180" viewBox="0 0 180 180">
  <rect width="180" height="180" fill="${PAPER}" />
  <rect x="${PAD}" y="${PAD}" width="${SEAL}" height="${SEAL}" rx="${(6 / 28) * SEAL}" fill="${CLAY}" />
  <text x="90" y="${PAD + 0.732 * SEAL}" text-anchor="middle" font-size="${(17 / 28) * SEAL}"
        font-family="Hiragino Sans, sans-serif" fill="${PAPER}">家</text>
</svg>`

await sharp(Buffer.from(svg), { density: 384 })
  .resize(180, 180)
  .flatten({ background: PAPER })
  .removeAlpha()
  .png()
  .toFile(join(publicDir, 'apple-touch-icon.png'))

console.log('wrote apple-touch-icon.png (180x180, opaque, full-bleed)')
