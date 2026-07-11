"""GET /api/goal/service — a read-only goal digest for Sukumo, our
household's sibling app (Sukumo's docs/API.md §4, docs/phases/PHASE-3-siblings.md).

Sukumo's dashboard wants to show "how's the house goal going" alongside the
other household apps without a human sitting there logged in. Kakeibo's
normal auth is a per-user JWT minted via the Mishka Hub login proxy
(app/auth.py) — that model doesn't fit a machine-to-machine call, and Sukumo
should never hold a household password (docs/AUTH.md's hard rule, applied
one level up). So this endpoint uses a completely separate, static bearer
token (``KAKEIBO_SERVICE_TOKEN``) instead of the JWT flow, checked with
``hmac.compare_digest`` to avoid a timing side-channel — the identical
pattern Michi shipped as MICHI_SERVICE_TOKEN.

Every number below is a read of state the authed API already serves
(routers/goals.py + engines/goals.py) — this module adds no new derivations,
just a machine-auth-friendly wrapper with Sukumo's agreed field names. The
real goal figures come from runtime config / DB rows as ever (docs/
PRIVATE.md's redaction scheme) — an unseeded goal answers 503, the same
"unconfigured feature" convention as a missing token.
"""
from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..dates import now_london
from ..db import get_session
from ..errors import KakeiboHTTPException
from ..models import Account, Goal, User
from .goals import _goal_dict

router = APIRouter(tags=["service"])

# The one goal Sukumo's bridge tile reports on (its docs call this "the
# house-goal snapshot") — the key is fixed system taxonomy (seed_goals.py),
# not a personal figure.
_SERVICE_GOAL_KEY = "house_deposit"


def _not_configured() -> KakeiboHTTPException:
    return KakeiboHTTPException(
        status_code=503,
        detail="The service endpoint isn't set up yet",
        code="service_not_configured",
    )


def _require_service_token(request: Request) -> None:
    settings = request.app.state.settings

    if not settings.service_token:
        raise _not_configured()

    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise KakeiboHTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
            code="unauthorized",
        )

    token = header.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings.service_token):
        raise KakeiboHTTPException(
            status_code=401,
            detail="Invalid service token",
            code="unauthorized",
        )


@router.get("/goal/service", dependencies=[Depends(_require_service_token)])
def goal_service(session: Session = Depends(get_session)) -> dict[str, Any]:
    # Kakeibo is single-user (CLAUDE.md) — the first user row is the
    # household user, the same resolution seed_goals.py uses.
    user = session.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise _not_configured()

    goal = session.scalar(select(Goal).where(Goal.user_id == user.id, Goal.key == _SERVICE_GOAL_KEY))
    # An unseeded/target-less goal means the real figures haven't been
    # configured locally yet (seed_goals.py's "absent -> not created") —
    # report unconfigured, never an invented number.
    if goal is None or goal.target_minor is None or goal.target_minor <= 0 or not goal.target_date:
        raise _not_configured()

    today = now_london().strftime("%Y-%m-%d")
    owned_account_ids = set(session.scalars(select(Account.id).where(Account.user_id == user.id)).all())
    detail = _goal_dict(session, goal, owned_account_ids, today)

    saved_minor = detail["current_minor"]
    target_minor = detail["target_minor"]
    # One decimal place, floored — percentages round *against* the user
    # (docs/ARCHITECTURE.md §6), and integer maths keeps floats out of the
    # money path.
    pct = (saved_minor * 1000) // target_minor / 10
    # The date the saved figure was actually observed: the latest snapshot in
    # the series, or the configured baseline date before any snapshots exist
    # (the same fallback _goal_dict applies to current_minor).
    as_of = detail["series"][-1]["date"] if detail["series"] else goal.baseline_date

    return {
        "goal_pence": target_minor,
        "saved_pence": saved_minor,
        "pct": pct,
        "pace_status": detail["status"],
        "as_of": as_of,
    }
