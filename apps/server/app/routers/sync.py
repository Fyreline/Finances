"""POST /api/sync/run + GET /api/sync/status — docs/API.md §5, §1c."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import SyncRun
from ..sync_service import sync_starling, sync_trading212

router = APIRouter(tags=["sync"])

# Gmail (Phase 5) isn't built yet — a request for it degrades to a
# `not_configured` sync_runs row rather than a 400, same honesty as an
# absent credential (docs/PLAN.md §6 rule 7). Trading 212 joined
# `starling` here in Phase 3 — it still degrades to `not_configured` on its
# own when no key/secret is set (sync_trading212's own NotConfigured path),
# it's just no longer routed through this generic "not built yet" stub.
_IMPLEMENTED_PROVIDERS = {"starling", "trading212"}


class SyncRunBody(BaseModel):
    providers: list[str] | None = None


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@router.post("/sync/run", status_code=202)
async def run_sync(
    body: SyncRunBody,
    request: Request,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    settings = request.app.state.settings
    requested = body.providers or ["starling"]

    run_ids: dict[str, int] = {}
    for provider in requested:
        if provider == "starling":
            run = await sync_starling(session, user_id, settings)
        elif provider == "trading212":
            run = await sync_trading212(session, user_id, settings)
        else:
            ts = _now_str()
            run = SyncRun(
                provider=provider,
                started_at=ts,
                finished_at=ts,
                status="not_configured",
                new_rows=0,
                detail=f"{provider} integration is not built yet"
                if provider not in _IMPLEMENTED_PROVIDERS
                else None,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
        run_ids[provider] = run.id

    return {"run_ids": run_ids}


def sync_status_payload(session: Session) -> dict:
    """Latest sync_runs row per provider (docs/API.md §5) — the highest `id`
    per `provider`, since ids are assigned in insertion order. Shared with
    `GET /api/summary/bubbles` (docs/phases/PHASE-7-dashboard.md item 6:
    the collapsed home is ONE fetch, and that fetch carries the header
    pill's sync status too)."""
    latest_ids = dict(
        session.execute(select(SyncRun.provider, SyncRun.id).order_by(SyncRun.id)).all()
    )
    if not latest_ids:
        return {"runs": []}
    rows = session.scalars(select(SyncRun).where(SyncRun.id.in_(latest_ids.values()))).all()
    return {
        "runs": [
            {
                "provider": r.provider,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "new_rows": r.new_rows,
                "detail": r.detail,
            }
            for r in sorted(rows, key=lambda r: r.provider)
        ]
    }


@router.get("/sync/status")
async def sync_status(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return sync_status_payload(session)
