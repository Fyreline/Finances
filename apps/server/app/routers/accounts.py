"""Accounts, balances, net worth — docs/API.md §5 "Accounts & balances".
Manual accounts are local-only writes to Kakeibo's own DB — never a write to
any bank/broker (docs/ARCHITECTURE.md §5, docs/PLAN.md §6 rule 6).

`GET /api/networth` also hosts S2 (emergency fund) and S4 (contractor gap) —
docs/phases/PHASE-9-personal-goals.md left the placement to judgement, and
both share this endpoint's accessible-cash/account data rather than adding
their own bubbles (docs/DESIGN.md §3b row 8, updated this phase).
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..balances import carry_forward_series, sum_series
from ..dates import now_london
from ..db import get_session
from ..engines.emergency_fund import emergency_fund_check
from ..engines.goals import month_end_deltas, project_goal
from ..engines.networth import net_worth_now, net_worth_series
from ..errors import KakeiboHTTPException
from ..insights_service import accessible_cash_minor, essential_monthly_minor
from ..models import Account, BalanceSnapshot, FinancialConfig, Goal
from .goals import _goal_dict

router = APIRouter(tags=["accounts"])

_STALE_AFTER_HOURS = 48
_NET_WORTH_WINDOW_DAYS = 90


def _account_status(latest_local_date: str | None) -> str:
    if latest_local_date is None:
        return "not_configured"
    today = now_london().date()
    latest = datetime.strptime(latest_local_date, "%Y-%m-%d").date()
    age_hours = (today - latest).days * 24
    return "stale" if age_hours > _STALE_AFTER_HOURS else "ok"


def _latest_snapshot(session: Session, account_id: int) -> BalanceSnapshot | None:
    return session.scalar(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id == account_id)
        .order_by(BalanceSnapshot.local_date.desc())
        .limit(1)
    )


@router.get("/accounts")
async def list_accounts(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    accounts = session.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.id)).all()
    out = []
    for account in accounts:
        latest = _latest_snapshot(session, account.id)
        out.append(
            {
                "id": account.id,
                "provider": account.provider,
                "name": account.name,
                "kind": account.kind,
                "latest_balance_minor": latest.balance_minor if latest else None,
                "latest_snapshot_date": latest.local_date if latest else None,
                "include_in_networth": bool(account.include_in_networth),
                "status": _account_status(latest.local_date if latest else None),
            }
        )
    return {"accounts": out}


class ManualAccountBody(BaseModel):
    name: str
    kind: str
    balance_minor: int


@router.post("/accounts/manual", status_code=201)
async def create_manual_account(
    body: ManualAccountBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    account = Account(
        user_id=user_id,
        provider="manual",
        provider_account_uid=None,
        name=body.name,
        kind=body.kind,
        currency="GBP",
    )
    session.add(account)
    session.commit()
    session.refresh(account)

    now = now_london()
    session.add(
        BalanceSnapshot(
            account_id=account.id,
            captured_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            local_date=now.strftime("%Y-%m-%d"),
            balance_minor=body.balance_minor,
            available_minor=body.balance_minor,
        )
    )
    session.commit()

    return {
        "account": {
            "id": account.id,
            "provider": account.provider,
            "name": account.name,
            "kind": account.kind,
            "latest_balance_minor": body.balance_minor,
        }
    }


class ManualBalanceBody(BaseModel):
    balance_minor: int
    local_date: str


@router.post("/accounts/{account_id}/balance")
async def add_manual_balance(
    account_id: int,
    body: ManualBalanceBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    account = session.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    if account is None:
        raise KakeiboHTTPException(status_code=404, detail="Account not found", code="not_found")

    now = now_london().strftime("%Y-%m-%d %H:%M:%S")
    snapshot = session.scalar(
        select(BalanceSnapshot).where(
            BalanceSnapshot.account_id == account_id, BalanceSnapshot.local_date == body.local_date
        )
    )
    if snapshot is None:
        snapshot = BalanceSnapshot(
            account_id=account_id,
            captured_at=now,
            local_date=body.local_date,
            balance_minor=body.balance_minor,
            available_minor=body.balance_minor,
        )
        session.add(snapshot)
    else:
        snapshot.captured_at = now
        snapshot.balance_minor = body.balance_minor
        snapshot.available_minor = body.balance_minor
    session.commit()

    return {"balance_minor": snapshot.balance_minor, "local_date": snapshot.local_date}


def _emergency_fund_payload(session: Session, user_id: int, today: str) -> dict:
    """S2 (docs/PLAN.md §4 S2, docs/phases/PHASE-9-personal-goals.md §2).
    `has_active_savings_goal` is true when a house-deposit/rebuild-style
    goal is active *and* behind — the exact case PHASE-9 §2's "deliberate
    trade-off" copy point calls out, not merely "a goal exists"."""
    goals = session.scalars(
        select(Goal).where(Goal.user_id == user_id, Goal.key.in_(("house_deposit", "t212_rebuild")))
    ).all()
    owned = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
    has_active_behind_goal = False
    for g in goals:
        try:
            ids = [int(i) for i in json.loads(g.source_account_ids or "[]") if int(i) in owned]
        except (TypeError, ValueError):
            ids = []
        series = sum_series(carry_forward_series(session, ids)) if ids else []
        current = series[-1][1] if series else g.baseline_minor
        deltas = month_end_deltas(series) if series else []
        proj = project_goal(
            target_minor=g.target_minor, target_date=g.target_date, current_minor=current, eval_date=today, deltas=deltas
        )
        if proj.status == "behind":
            has_active_behind_goal = True

    return emergency_fund_check(
        accessible_cash_minor=accessible_cash_minor(session, user_id),
        essential_monthly_minor=essential_monthly_minor(session, user_id, today),
        has_active_savings_goal=has_active_behind_goal,
    )


def _contractor_gap_payload(session: Session, user_id: int, today: str) -> dict:
    """S4 (docs/PLAN.md §4 S4, docs/phases/PHASE-9-personal-goals.md §3).
    `pension_contributing` renders tri-state (`None` = "not sure yet — check
    with your consultancy", never assumed `False`, docs/PRIVATE.md). The
    `fte_runway` goal (if `fte_conversion_target_date` is set) is surfaced
    via the same `_goal_dict` shape `GET /api/goals` returns — no new goal
    endpoint, per the phase spec."""
    config = session.get(FinancialConfig, user_id)
    pension_contributing = None if config is None or config.pension_contributing is None else bool(config.pension_contributing)
    fte_target_date = config.fte_conversion_target_date if config else None

    fte_runway_goal = None
    if fte_target_date:
        goal = session.scalar(select(Goal).where(Goal.user_id == user_id, Goal.key == "fte_runway"))
        if goal is not None:
            owned = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
            fte_runway_goal = _goal_dict(session, goal, owned, today)

    return {
        "pension_contributing": pension_contributing,
        "fte_conversion_target_date": fte_target_date,
        "fte_runway_goal": fte_runway_goal,
    }


def networth_payload(session: Session, user_id: int) -> dict:
    """Shared by `GET /api/networth` and `GET /api/summary/bubbles`
    (docs/phases/PHASE-9-personal-goals.md §1 "extend bubbles_payload(),
    don't add a second round-trip") — same function, same result, so the
    Net Worth bubble's glance can never disagree with its own detail view."""
    today = now_london().strftime("%Y-%m-%d")
    accounts = session.scalars(
        select(Account).where(Account.user_id == user_id, Account.include_in_networth == 1)
    ).all()
    account_ids = [a.id for a in accounts]

    dated_totals = carry_forward_series(session, account_ids)
    now = net_worth_now([{"id": a.id, "name": a.name} for a in accounts], dated_totals)
    series = net_worth_series(dated_totals, window_days=_NET_WORTH_WINDOW_DAYS)
    as_of = dated_totals[-1][0] if dated_totals else None

    return {
        "total_minor": now["total_minor"],
        "by_account": now["by_account"],
        "series": series,
        "as_of": as_of,
        "emergency_fund": _emergency_fund_payload(session, user_id, today),
        "contractor_gap": _contractor_gap_payload(session, user_id, today),
    }


@router.get("/networth")
async def networth(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return networth_payload(session, user_id)
