"""Accounts, balances, net worth — docs/API.md §5 "Accounts & balances".
Manual accounts are local-only writes to Kakeibo's own DB — never a write to
any bank/broker (docs/ARCHITECTURE.md §5, docs/PLAN.md §6 rule 6).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..balances import carry_forward_series
from ..dates import now_london
from ..db import get_session
from ..errors import KakeiboHTTPException
from ..models import Account, BalanceSnapshot

router = APIRouter(tags=["accounts"])

_STALE_AFTER_HOURS = 48


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


@router.get("/networth")
async def networth(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    accounts = session.scalars(
        select(Account).where(Account.user_id == user_id, Account.include_in_networth == 1)
    ).all()
    account_ids = [a.id for a in accounts]

    dated_totals = carry_forward_series(session, account_ids)
    series = [
        {"date": d, "total_minor": sum(by_account.values()), "by_account": by_account}
        for d, by_account in dated_totals
    ]

    as_of = dated_totals[-1][0] if dated_totals else None
    return {"series": series, "as_of": as_of}
