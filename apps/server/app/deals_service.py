"""Import orchestration for the Deals feature (docs/API.md §4). Scans
``data/deals/`` for research-run JSON files and imports the newest one into
``deal_runs``/``savings_deals``, idempotently per file — a file already
imported (matched by its ``file_path``) is a no-op, never a duplicate row
(docs/phases/PHASE-6-deals-splits.md acceptance: "Import is idempotent per
file; newest run wins the display"). Called from both the
``POST /api/deals/import`` route and server startup (``main.py``'s lifespan,
mirroring the ``seed_categories``/``seed_goals``/``seed_tax_years``
precedent already established there).
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engines.deals import load_deal_run_file, newest_deal_run_file
from .models import DealRun, SavingsDeal


def import_newest_deal_run(session: Session, deals_dir: Path) -> tuple[DealRun | None, int]:
    """Returns ``(run, deals_imported_this_call)``. ``deals_imported_this_call``
    is ``0`` when the newest file was already imported (idempotent) or no
    file exists yet; the returned ``run`` is still the newest known run in
    that idempotent case, so callers don't need a second lookup.

    Raises ``DealRunValidationError`` (docs/engines/deals.py) if the newest
    file exists but fails schema validation — the caller decides whether that
    becomes an HTTP 400 (the router) or a logged skip (startup).
    """
    if not deals_dir.exists():
        return None, 0
    path = newest_deal_run_file(deals_dir)
    if path is None:
        return None, 0

    existing = session.scalar(select(DealRun).where(DealRun.file_path == str(path)))
    if existing is not None:
        return existing, 0

    payload = load_deal_run_file(path)  # raises DealRunValidationError on a malformed file
    run = DealRun(
        run_at=payload["run_at"],
        method=payload["method"],
        sources_json=json.dumps(payload["sources"]),
        file_path=str(path),
    )
    session.add(run)
    session.flush()
    for deal in payload["deals"]:
        session.add(
            SavingsDeal(
                deal_run_id=run.id,
                provider=deal["provider"],
                product=deal["product"],
                aer_pct=deal["aer_pct"],
                access=deal["access"],
                min_deposit_minor=deal.get("min_deposit_minor"),
                fscs=1 if deal.get("fscs", True) else 0,
                is_isa=1 if deal.get("is_isa", False) else 0,
                source_url=deal["source_url"],
                notes=deal.get("notes"),
            )
        )
    session.commit()
    session.refresh(run)
    return run, len(payload["deals"])
