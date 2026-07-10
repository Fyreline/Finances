"""Savings-deals research feature — docs/API.md §4/§5 "Deals",
docs/DESIGN.md §4h, docs/phases/PHASE-6-deals-splits.md.

Not a live feed: ``data/deals/*.json`` files are dated, source-cited research
runs written by a periodic agent task or a manual ritual
(docs/DEPLOYMENT.md §4d, ``scripts/research_deals_prompt.md``).
``deals_service.import_newest_deal_run`` owns turning the newest such file
into ``deal_runs``/``savings_deals`` rows; this router serves the result with
its as-of date always attached, and exposes the same import as a manual
``POST`` for whenever a human wants to trigger it without restarting the
server.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import DATA_DIR
from ..db import get_session
from ..deals_service import import_newest_deal_run
from ..engines.deals import DealRunValidationError, is_stale, parse_run_at
from ..errors import KakeiboHTTPException
from ..models import DealRun, SavingsDeal

router = APIRouter(tags=["deals"])

DEALS_DIR = DATA_DIR / "deals"


def _serialise_deal(deal: SavingsDeal) -> dict:
    return {
        "id": deal.id,
        "provider": deal.provider,
        "product": deal.product,
        "aer_pct": deal.aer_pct,
        "access": deal.access,
        "min_deposit_minor": deal.min_deposit_minor,
        "fscs": bool(deal.fscs),
        "is_isa": bool(deal.is_isa),
        "source_url": deal.source_url,
        "notes": deal.notes,
    }


def deals_payload(session: Session) -> dict:
    """Newest research run + its deals — shared by `GET /api/deals` and
    `GET /api/summary/bubbles` (docs/phases/PHASE-7-dashboard.md item 6)."""
    # "newest run wins the display" — order by the run's own research date,
    # not import order, so a backfilled older file never displaces a newer
    # one that happened to be imported first.
    run = session.scalar(select(DealRun).order_by(DealRun.run_at.desc(), DealRun.id.desc()).limit(1))
    if run is None:
        return {"run": None, "deals": [], "stale": False}

    deals = session.scalars(
        select(SavingsDeal).where(SavingsDeal.deal_run_id == run.id).order_by(SavingsDeal.aer_pct.desc())
    ).all()
    return {
        "run": {"run_at": run.run_at, "sources": json.loads(run.sources_json)},
        "deals": [_serialise_deal(d) for d in deals],
        "stale": is_stale(parse_run_at(run.run_at)),
    }


@router.get("/deals")
async def get_deals(_user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return deals_payload(session)


@router.post("/deals/import")
async def import_deals(_user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    try:
        _run, imported = import_newest_deal_run(session, DEALS_DIR)
    except DealRunValidationError as exc:
        raise KakeiboHTTPException(status_code=400, detail=str(exc), code="invalid_deal_run") from exc
    return {"imported": imported}
