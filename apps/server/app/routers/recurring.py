"""GET /api/recurring + PATCH /api/recurring/{id} — docs/API.md §5 "Recurring",
detection maths in docs/DATA_MODEL.md §3a via `engines/recurring` +
`insights_service`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..errors import KakeiboHTTPException
from ..insights_service import list_recurring_payload
from ..models import RecurringPayment

router = APIRouter(tags=["recurring"])

_VERDICTS = {"keep", "cancel_candidate", "cancelled"}


@router.get("/recurring")
async def list_recurring(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return list_recurring_payload(session, user_id)


class RecurringPatchBody(BaseModel):
    user_verdict: str


@router.patch("/recurring/{recurring_id}")
async def patch_recurring(
    recurring_id: int,
    body: RecurringPatchBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    if body.user_verdict not in _VERDICTS:
        raise KakeiboHTTPException(
            status_code=400, detail=f"user_verdict must be one of {sorted(_VERDICTS)}", code="invalid_verdict"
        )
    row = session.get(RecurringPayment, recurring_id)
    if row is None or row.user_id != user_id:
        raise KakeiboHTTPException(status_code=404, detail="Recurring payment not found", code="not_found")

    row.user_verdict = body.user_verdict
    # A "cancelled" verdict also dismisses the row from active committed totals
    # and stops it resurfacing as a cancel-candidate (docs/DATA_MODEL.md §3a.5).
    if body.user_verdict == "cancelled":
        row.status = "dismissed"
    session.commit()
    return {"recurring": {"id": row.id, "user_verdict": row.user_verdict, "status": row.status}}
