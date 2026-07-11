"""Personal wants — docs/PLAN.md §3 row 11 (refined), docs/phases/
PHASE-9-personal-goals.md §5. CRUD + a live affordability verdict per
unbought item (`engines/affordability.py`), checked against this period's
safe-to-spend headroom (Phase 4) and the house-deposit goal's projection run
before/after the item's price (Phase 3) — composed here, computed nowhere
else (docs/ARCHITECTURE.md §3).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..balances import carry_forward_series, sum_series
from ..dates import now_london
from ..db import get_session
from ..engines.affordability import check_affordability
from ..engines.goals import GoalProjection, month_end_deltas, project_goal
from ..errors import KakeiboHTTPException
from ..insights_service import safe_to_spend_payload
from ..models import Account, Goal, WantItem

router = APIRouter(prefix="/wants", tags=["wants"])


def _house_deposit_projection(session: Session, user_id: int, today: str, *, price_minor: int) -> GoalProjection | None:
    """Runs `project_goal` for `house_deposit` with its current balance
    reduced by `price_minor` (0 for the "before" call) — the exact "goals
    engine before/after" mechanic docs/phases/PHASE-9 §5 specifies. `None`
    when no house_deposit goal is configured yet (fresh-setup state)."""
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id, Goal.key == "house_deposit"))
    if goal is None:
        return None
    owned = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
    try:
        ids = [int(i) for i in json.loads(goal.source_account_ids or "[]") if int(i) in owned]
    except (TypeError, ValueError):
        ids = []
    series = sum_series(carry_forward_series(session, ids)) if ids else []
    current = series[-1][1] if series else goal.baseline_minor
    deltas = month_end_deltas(series) if series else []
    return project_goal(
        target_minor=goal.target_minor,
        target_date=goal.target_date,
        current_minor=current - price_minor,
        eval_date=today,
        deltas=deltas,
    )


def _affordability_for(session: Session, user_id: int, price_minor: int, today: str) -> dict:
    headroom = safe_to_spend_payload(session, user_id, today=today)["remaining_minor"]
    before = _house_deposit_projection(session, user_id, today, price_minor=0)
    after = _house_deposit_projection(session, user_id, today, price_minor=price_minor)
    return check_affordability(price_minor, headroom, before, after)


def _want_dict(session: Session, user_id: int, item: WantItem, today: str) -> dict:
    return {
        "id": item.id,
        "label": item.label,
        "price_minor": item.price_minor,
        "bought": bool(item.bought),
        "created_at": item.created_at,
        # A bought item has already happened — no live verdict to show.
        "affordability": None if item.bought else _affordability_for(session, user_id, item.price_minor, today),
    }


def wants_payload(session: Session, user_id: int) -> dict:
    today = now_london().strftime("%Y-%m-%d")
    items = session.scalars(select(WantItem).where(WantItem.user_id == user_id).order_by(WantItem.id)).all()
    return {"wants": [_want_dict(session, user_id, i, today) for i in items]}


@router.get("")
async def list_wants(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return wants_payload(session, user_id)


class WantCreateBody(BaseModel):
    label: str
    price_minor: int


@router.post("", status_code=201)
async def create_want(
    body: WantCreateBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    if body.price_minor <= 0:
        raise KakeiboHTTPException(status_code=400, detail="price_minor must be positive", code="invalid_price")
    item = WantItem(user_id=user_id, label=body.label, price_minor=body.price_minor)
    session.add(item)
    session.commit()
    session.refresh(item)
    today = now_london().strftime("%Y-%m-%d")
    return {"want": _want_dict(session, user_id, item, today)}


class WantPatchBody(BaseModel):
    label: str | None = None
    price_minor: int | None = None
    bought: bool | None = None


def _get_owned_want(session: Session, user_id: int, item_id: int) -> WantItem:
    item = session.scalar(select(WantItem).where(WantItem.id == item_id, WantItem.user_id == user_id))
    if item is None:
        raise KakeiboHTTPException(status_code=404, detail="Want not found", code="not_found")
    return item


@router.patch("/{item_id}")
async def patch_want(
    item_id: int, body: WantPatchBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    item = _get_owned_want(session, user_id, item_id)
    patch = body.model_dump(exclude_unset=True)
    if "price_minor" in patch and patch["price_minor"] is not None and patch["price_minor"] <= 0:
        raise KakeiboHTTPException(status_code=400, detail="price_minor must be positive", code="invalid_price")
    if "label" in patch and patch["label"] is not None:
        item.label = patch["label"]
    if "price_minor" in patch and patch["price_minor"] is not None:
        item.price_minor = patch["price_minor"]
    if "bought" in patch and patch["bought"] is not None:
        item.bought = int(patch["bought"])
    session.commit()
    session.refresh(item)
    today = now_london().strftime("%Y-%m-%d")
    return {"want": _want_dict(session, user_id, item, today)}


@router.delete("/{item_id}")
async def delete_want(
    item_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    item = _get_owned_want(session, user_id, item_id)
    session.delete(item)
    session.commit()
    return {"deleted": True}
