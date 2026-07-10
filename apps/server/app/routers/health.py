"""GET /api/health — docs/AUTH.md §3: "liveness + integration reachability
flags only — never balances or counts". Public (no auth), same as login/
refresh. The Mishka Hub reachability probe uses a 1s timeout
(identity.py's ``ping``) and is cached for 60s at module scope so health
checks don't hammer or block on Mishka Hub.
"""
from __future__ import annotations

import calendar
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import SyncRun

router = APIRouter(tags=["health"])

_CACHE_TTL_SECONDS = 60
_cache: dict[str, float | bool] = {"checked_at": 0.0, "reachable": False}


async def _identity_reachable(request: Request) -> bool:
    now = time.monotonic()
    if now - _cache["checked_at"] < _CACHE_TTL_SECONDS:
        return bool(_cache["reachable"])
    identity = request.app.state.identity
    reachable = await identity.ping()
    _cache["checked_at"] = now
    _cache["reachable"] = reachable
    return reachable


_STALE_AFTER_SECONDS = 48 * 3600  # matches /api/accounts' "stale = no snapshot 48h"


def _provider_status(configured: bool, last_run: SyncRun | None, now_ts: float) -> tuple[str, str | None]:
    """docs/API.md §5 health shape: `"ok"|"not_configured"|"error"|"stale"`
    plus the last successful sync timestamp (or null). Flags and a timestamp
    only — never balances or counts (docs/AUTH.md §3)."""
    if not configured:
        return "not_configured", None
    if last_run is None:
        return "ok", None  # configured but never synced yet
    last_ok = last_run.finished_at if last_run.status == "ok" else None
    if last_run.status == "error":
        return "error", None
    if last_ok:
        parsed = time.strptime(last_ok, "%Y-%m-%d %H:%M:%S")
        if now_ts - calendar.timegm(parsed) > _STALE_AFTER_SECONDS:
            return "stale", last_ok
    return "ok", last_ok


@router.get("/health")
async def health(request: Request, session: Session = Depends(get_session)) -> dict:
    reachable = await _identity_reachable(request)
    settings = request.app.state.settings
    # Latest sync_runs row per provider (highest id wins, insertion order).
    latest_ids = dict(session.execute(select(SyncRun.provider, SyncRun.id).order_by(SyncRun.id)).all())
    latest: dict[str, SyncRun] = {}
    if latest_ids:
        for row in session.scalars(select(SyncRun).where(SyncRun.id.in_(latest_ids.values()))):
            latest[row.provider] = row
    now_ts = time.time()
    configured = {
        "starling": settings.starling_configured,
        "trading212": settings.t212_configured,
        "gmail": settings.gmail_configured,
    }
    integrations: dict[str, str] = {}
    last_sync: dict[str, str | None] = {}
    for provider, is_configured in configured.items():
        status, last_ok = _provider_status(is_configured, latest.get(provider), now_ts)
        integrations[provider] = status
        last_sync[provider] = last_ok
    return {
        "status": "ok",
        "identity": "reachable" if reachable else "unreachable",
        # No balances, no counts, no personal data (docs/AUTH.md §3) — every
        # integration is "not_configured" until real credentials land
        # (docs/SECRETS.md; PLAN.md §6 rule 7).
        "integrations": integrations,
        "last_sync": last_sync,
    }
