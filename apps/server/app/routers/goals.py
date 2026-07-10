"""GET/PATCH /api/goals — docs/API.md §5 "Goals", projection maths from
docs/DATA_MODEL.md §4a via `engines/goals.py`.
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
from ..engines.goals import month_end_deltas, project_goal
from ..errors import KakeiboHTTPException
from ..models import Account, Goal

router = APIRouter(tags=["goals"])


def _source_account_ids(goal: Goal, owned_account_ids: set[int]) -> list[int]:
    try:
        raw_ids = json.loads(goal.source_account_ids or "[]")
    except (TypeError, ValueError):
        raw_ids = []
    # Only ever aggregate accounts this user actually owns, even if
    # source_account_ids somehow drifted (defence in depth — PATCH is the
    # only writer and it's authenticated, but this keeps the read side
    # honest regardless).
    return [int(i) for i in raw_ids if isinstance(i, int | str) and int(i) in owned_account_ids]


def _goal_dict(session: Session, goal: Goal, owned_account_ids: set[int], today: str) -> dict:
    account_ids = _source_account_ids(goal, owned_account_ids)
    dated_totals = carry_forward_series(session, account_ids) if account_ids else []
    series = sum_series(dated_totals)

    # "The dashboard's first render should show the equivalent computed
    # figure for the real, locally-configured goal" (docs/DATA_MODEL.md
    # §4a) — before any snapshot exists for this goal's source accounts
    # (or none are configured yet), the baseline stands in for the current
    # balance.
    current_minor = series[-1][1] if series else goal.baseline_minor
    deltas = month_end_deltas(series) if series else []

    projection = project_goal(
        target_minor=goal.target_minor,
        target_date=goal.target_date,
        current_minor=current_minor,
        eval_date=today,
        deltas=deltas,
    )

    return {
        "key": goal.key,
        "label": goal.label,
        "target_minor": goal.target_minor,
        "target_date": goal.target_date,
        "current_minor": current_minor,
        "baseline_minor": goal.baseline_minor,
        "baseline_date": goal.baseline_date,
        "monthly_pledge_minor": goal.monthly_pledge_minor,
        "required_per_month_minor": projection.required_per_month_minor,
        "trend_per_month_minor": projection.trend_per_month_minor,
        "projected_at_target_minor": projection.projected_at_target_minor,
        "status": projection.status,
        "catch_up_per_month_minor": projection.catch_up_per_month_minor,
        "series": [{"date": d, "value_minor": v} for d, v in series],
    }


def goals_payload(session: Session, user_id: int) -> dict:
    """Every goal with its full projection — shared by `GET /api/goals` and
    `GET /api/summary/bubbles` (docs/phases/PHASE-7-dashboard.md item 6)."""
    today = now_london().strftime("%Y-%m-%d")
    goals = session.scalars(select(Goal).where(Goal.user_id == user_id).order_by(Goal.id)).all()
    owned_account_ids = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
    return {"goals": [_goal_dict(session, g, owned_account_ids, today) for g in goals]}


@router.get("/goals")
async def list_goals(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return goals_payload(session, user_id)


class GoalPatchBody(BaseModel):
    monthly_pledge_minor: int | None = None
    target_minor: int | None = None
    source_account_ids: list[int] | None = None


@router.patch("/goals/{key}")
async def patch_goal(
    key: str,
    body: GoalPatchBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    goal = session.scalar(select(Goal).where(Goal.user_id == user_id, Goal.key == key))
    if goal is None:
        raise KakeiboHTTPException(status_code=404, detail="Goal not found", code="not_found")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise KakeiboHTTPException(status_code=400, detail="No fields to update", code="empty_patch")

    if "monthly_pledge_minor" in patch:
        goal.monthly_pledge_minor = patch["monthly_pledge_minor"]
    if "target_minor" in patch:
        goal.target_minor = patch["target_minor"]
    if "source_account_ids" in patch:
        ids = patch["source_account_ids"] or []
        owned = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
        unknown = [i for i in ids if i not in owned]
        if unknown:
            raise KakeiboHTTPException(
                status_code=400, detail=f"Unknown or not-owned account ids: {unknown}", code="invalid_account"
            )
        goal.source_account_ids = json.dumps(ids)

    session.commit()
    session.refresh(goal)

    today = now_london().strftime("%Y-%m-%d")
    owned_account_ids = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
    return {"goal": _goal_dict(session, goal, owned_account_ids, today)}
