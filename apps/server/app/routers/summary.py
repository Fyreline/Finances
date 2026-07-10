"""Safe-to-spend, monthly breakdown, tips, and the financial-config form —
docs/API.md §5 "Summary & insights" + §6a/§6b/§6c. Thin: every number comes
from `insights_service` over the pure engines (docs/ARCHITECTURE.md §3).

Note: docs/API.md §5 lists the summary/tips endpoints but omits a
`financial_config` read/write endpoint, even though §6a depends on that config
and docs/phases/PHASE-4-insights.md item 1 requires the form. Added here as
`GET/PUT /api/financial-config` (parallel to `GET/PUT /api/tax/config`); API.md
§5 corrected to match in the same commit.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func, select

from ..auth import current_user
from ..dates import now_london, tax_year_of
from ..db import get_session
from ..errors import KakeiboHTTPException
from ..insights_service import (
    list_recurring_payload,
    list_tips_payload,
    month_summary_payload,
    safe_to_spend_payload,
)
from ..models import FinancialConfig, TaxDocument, Tip
from .deals import deals_payload
from .goals import goals_payload
from .sync import sync_status_payload
from .tax import year_summary_payload

router = APIRouter(tags=["summary"])

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_SETASIDE_MODES = {"auto", "fixed", "off"}


@router.get("/summary/bubbles")
async def get_bubbles(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    """Every bubble's collapsed glance payload in ONE call — the home screen
    renders from this single fetch (docs/phases/PHASE-7-dashboard.md item 6:
    "the collapsed home should be ONE fetch"). Each sub-payload is exactly
    what the matching standalone endpoint returns (same shared functions),
    so expanding a bubble later never disagrees with its glance. The tax
    entry is the §3b row-6 glance shape only — profit so far, the estimate
    figure (or how many inputs it still needs — it never guesses,
    docs/TAX.md §0), and the unreviewed-documents count."""
    now = now_london()
    month = now.strftime("%Y-%m")
    tax_year = tax_year_of(now.strftime("%Y-%m-%d"))

    tax_summary = year_summary_payload(session, user_id, tax_year)
    estimate = tax_summary["estimate"]
    unreviewed = session.scalar(
        select(func.count()).select_from(TaxDocument).where(TaxDocument.reviewed == 0)
    )

    return {
        "month": month,
        "safe_to_spend": safe_to_spend_payload(session, user_id),
        "goals": goals_payload(session, user_id)["goals"],
        "month_summary": month_summary_payload(session, user_id, month),
        "tips_count": len(list_tips_payload(session, user_id, month)["tips"]),
        "recurring": list_recurring_payload(session, user_id),
        "deals": deals_payload(session),
        "tax": {
            "tax_year": tax_year,
            "profit_minor": tax_summary["profit_minor"],
            "estimated_tax_minor": estimate["tax_due_minor"] if estimate else None,
            "missing_inputs_count": len(tax_summary["missing_inputs"]),
            "unreviewed_documents": unreviewed or 0,
        },
        "sync": sync_status_payload(session),
    }


@router.get("/summary/safe-to-spend")
async def get_safe_to_spend(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return safe_to_spend_payload(session, user_id)


@router.get("/summary/month/{month}")
async def get_month_summary(
    month: str, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    if not _MONTH_RE.match(month):
        raise KakeiboHTTPException(status_code=400, detail="month must be YYYY-MM", code="invalid_month")
    return month_summary_payload(session, user_id, month)


@router.get("/tips")
async def get_tips(
    period: str | None = None, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    period = period or now_london().strftime("%Y-%m")
    if not _MONTH_RE.match(period):
        raise KakeiboHTTPException(status_code=400, detail="period must be YYYY-MM", code="invalid_period")
    return list_tips_payload(session, user_id, period)


@router.post("/tips/{tip_id}/dismiss")
async def dismiss_tip(
    tip_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    tip = session.get(Tip, tip_id)
    if tip is None or tip.user_id != user_id:
        raise KakeiboHTTPException(status_code=404, detail="Tip not found", code="not_found")
    tip.dismissed = 1
    session.commit()
    return {"dismissed": True}


# --------------------------------------------------------- financial config
def _financial_config_dict(row: FinancialConfig) -> dict:
    return {
        "payday_day": row.payday_day,
        "net_monthly_income_minor": row.net_monthly_income_minor,
        "flat_share_minor": row.flat_share_minor,
        "buffer_minor": row.buffer_minor,
        "tax_setaside_mode": row.tax_setaside_mode,
        "tax_setaside_fixed_minor": row.tax_setaside_fixed_minor,
    }


def _get_or_create_config(session: Session, user_id: int) -> FinancialConfig:
    row = session.get(FinancialConfig, user_id)
    if row is None:
        row = FinancialConfig(user_id=user_id, updated_at=now_london().strftime("%Y-%m-%d %H:%M:%S"))
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@router.get("/financial-config")
async def get_financial_config(
    user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    return {"financial_config": _financial_config_dict(_get_or_create_config(session, user_id))}


class FinancialConfigBody(BaseModel):
    payday_day: int | None = None
    net_monthly_income_minor: int | None = None
    flat_share_minor: int | None = None
    buffer_minor: int | None = None
    tax_setaside_mode: str | None = None
    tax_setaside_fixed_minor: int | None = None


@router.put("/financial-config")
async def put_financial_config(
    body: FinancialConfigBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if "payday_day" in patch and patch["payday_day"] is not None and not 1 <= patch["payday_day"] <= 31:
        raise KakeiboHTTPException(status_code=400, detail="payday_day must be 1-31", code="invalid_payday")
    if "tax_setaside_mode" in patch and patch["tax_setaside_mode"] not in _SETASIDE_MODES:
        raise KakeiboHTTPException(
            status_code=400, detail=f"tax_setaside_mode must be one of {sorted(_SETASIDE_MODES)}", code="invalid_mode"
        )

    row = _get_or_create_config(session, user_id)
    for field, value in patch.items():
        setattr(row, field, value)
    row.updated_at = now_london().strftime("%Y-%m-%d %H:%M:%S")
    session.commit()
    session.refresh(row)
    return {"financial_config": _financial_config_dict(row)}
