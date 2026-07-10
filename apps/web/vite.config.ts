import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// For GitHub Pages *project* sites the app is served from /<repo>/, so a
// deploy workflow (Phase 8) sets VITE_BASE=/Finances/ at build time
// (docs/ARCHITECTURE.md §2). Defaults to '/' for local dev. Kakeibo's dev
// server owns port 5178 — Mishka Hub's owns 5173, Michi's 5174 — so all
// three can run side-by-side on the household machine.
const BASE = process.env.VITE_BASE ?? '/'

export default defineConfig({
  base: BASE,
  plugins: [react(), tailwindcss()],
  server: { port: 5178 },
  test: {
    environment: 'jsdom',
  },
})
