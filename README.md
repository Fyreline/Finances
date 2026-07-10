# Kakeibo 家計簿

A calm, single-household personal finance dashboard: read-only pulls from Starling
Bank and Trading 212, rental paperwork gathered from Gmail, and a hand-rolled-SVG
bubble home screen that turns them into a safe-to-spend number, goal projections,
spending verdicts, recurring-payment detection, and a UK Self Assessment estimate
that refuses to guess. Everything is integer pence, everything is read-only against
the banks (by credential scope *and* code shape), and nothing personal is committed —
this repo is public, the money data never leaves the household machine.

<!-- TODO(human, ship day): one screenshot of the bubble home screen at
     docs/assets/home.png — capture it with real-ish local data, check nothing
     personal is legible, and embed it here. -->

The full spec lives in [`docs/`](docs/) — start with [`docs/PLAN.md`](docs/PLAN.md)
(what and why), then [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (how),
[`docs/HANDOFF.md`](docs/HANDOFF.md) (current state, open questions), and
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) (the runbook). Kakeibo's tax numbers are
planning estimates only — not tax advice, and never a substitute for HMRC's own
calculators or an accountant ([`docs/TAX.md`](docs/TAX.md) §0).
