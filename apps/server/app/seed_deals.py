"""Deals-directory bootstrap (docs/phases/PHASE-6-deals-splits.md item 3:
"seed one research run at build time... so the bubble ships alive").

**Design note, not a doc contradiction (docs/PLAN.md §6 rule 1 — recorded for
the record):** docs/ARCHITECTURE.md §5 lists ``data/deals/`` alongside
``data/*.db``/``tax-documents/`` as gitignored, household-Mac-only — the
public repo never carries a committed JSON file there. So "seed one research
run at build time" is read here the same way this codebase already reads
that exact instruction for goals/categories/tax-years: a small, idempotent,
**code** seed that runs at server startup (``main.py``'s lifespan), not a
data file checked into git. A real monthly research run
(``scripts/research_deals_prompt.md``, docs/DEPLOYMENT.md §4d) simply drops a
newer dated file into ``data/deals/`` and this placeholder stops being the
newest run — nothing further to migrate.

The seeded file is unambiguously synthetic — obviously placeholder provider
name, an explicit "SYNTHETIC TEST DATA" marker in two separate fields, and an
``.invalid`` source URL (RFC 2606) that cannot resolve to a real page — so it
can never be mistaken for real financial research (docs/PLAN.md's hard
constraint on this phase).
"""
from __future__ import annotations

import json
from pathlib import Path

from .dates import now_london


def seed_deals(deals_dir: Path) -> Path | None:
    """Write one synthetic placeholder research-run file if ``deals_dir`` has
    no research runs yet. Never overwrites or removes an existing file — the
    moment a real run (seeded here or dropped in for real) exists, this is a
    permanent no-op. Returns the path written, or ``None`` if it was a no-op.
    """
    deals_dir.mkdir(parents=True, exist_ok=True)
    if any(deals_dir.glob("*.json")):
        return None

    now = now_london()
    run_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "run_at": run_at,
        "method": "manual",
        "sources": [
            {"url": "https://example.invalid/synthetic-fixture", "fetched_at": run_at},
        ],
        "deals": [
            {
                "provider": "Example Building Society (SYNTHETIC TEST DATA)",
                "product": "Placeholder Easy Access — not a real product",
                "aer_pct": 4.50,
                "access": "easy",
                "min_deposit_minor": 0,
                "fscs": True,
                "is_isa": False,
                "source_url": "https://example.invalid/synthetic-fixture",
                "notes": (
                    "SYNTHETIC TEST DATA — not a real rate or provider. Seeded at server "
                    "startup so the Deals bubble renders end-to-end before the first real "
                    "research run (docs/DEPLOYMENT.md §4d, scripts/research_deals_prompt.md)."
                ),
            }
        ],
    }
    path = deals_dir / f"{now.strftime('%Y-%m-%d')}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path
