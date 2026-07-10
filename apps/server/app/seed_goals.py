"""Seeds `house_deposit` / `t212_rebuild` / `emergency_fund` goal rows from
local, gitignored config — docs/phases/PHASE-3-t212-goals.md item 4,
docs/PRIVATE.md's redaction scheme. Mirrors the
`KAKEIBO_STARLING_BACKFILL_START` precedent from Phase 2 (docs/API.md §1c):
every value here is an optional env var, empty by default, and absence means
the goal simply isn't created yet — its bubble stays in the setup state
rather than being seeded with an invented number.

Idempotent like `seed_categories`, but NOT the same idempotency shape: a
goal that already exists is left alone here (never overwritten) — restarting
the API must not stomp a real user edit made via `PATCH /api/goals/{key}`
(target_minor, monthly_pledge_minor, source_account_ids) with whatever the
current `.env` happens to say. Categories are fixed system taxonomy and get
re-synced every boot; goals are user data and only get created once.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .dates import now_london
from .models import Goal, User


def _minor_or_none(value: str) -> int | None:
    return int(value) if value else None


def seed_goals(session: Session, settings: Settings, user_id: int | None = None) -> None:
    if user_id is None:
        user = session.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            return  # nobody has logged in yet — nothing to seed against
        user_id = user.id

    existing_keys = {g.key for g in session.scalars(select(Goal).where(Goal.user_id == user_id)).all()}

    t212_baseline_minor = _minor_or_none(settings.goal_t212_rebuild_baseline_minor)
    t212_baseline_date = settings.goal_t212_rebuild_baseline_date or None

    if "t212_rebuild" not in existing_keys and t212_baseline_minor is not None and t212_baseline_date:
        session.add(
            Goal(
                user_id=user_id,
                key="t212_rebuild",
                label="Trading 212 rebuild",
                target_minor=None,  # open-ended (docs/DATA_MODEL.md §4)
                target_date=None,
                baseline_minor=t212_baseline_minor,
                baseline_date=t212_baseline_date,
                source_account_ids="[]",
            )
        )

    deposit_target_minor = _minor_or_none(settings.goal_house_deposit_target_minor)
    deposit_target_date = settings.goal_house_deposit_target_date or None
    # The deposit's baseline defaults to the T212 rebuild's — this user's
    # rebuilding pot IS his house-deposit fund today (docs/PRIVATE.md); an
    # explicit KAKEIBO_GOAL_HOUSE_DEPOSIT_BASELINE_* pair overrides that if
    # a separate deposit-specific baseline is ever configured.
    deposit_baseline_minor = _minor_or_none(settings.goal_house_deposit_baseline_minor) or t212_baseline_minor
    deposit_baseline_date = settings.goal_house_deposit_baseline_date or t212_baseline_date

    if (
        "house_deposit" not in existing_keys
        and deposit_target_minor is not None
        and deposit_target_date
        and deposit_baseline_minor is not None
        and deposit_baseline_date
    ):
        session.add(
            Goal(
                user_id=user_id,
                key="house_deposit",
                label="House deposit",
                target_minor=deposit_target_minor,
                target_date=deposit_target_date,
                baseline_minor=deposit_baseline_minor,
                baseline_date=deposit_baseline_date,
                source_account_ids="[]",
            )
        )

    if "emergency_fund" not in existing_keys:
        # Stub (docs/phases/PHASE-3-t212-goals.md item 4): the real target is
        # `3 x essential_monthly_spend`, which Phase 4's insight engine
        # supplies (docs/DATA_MODEL.md §4a). baseline 0 / today is a
        # placeholder marker, not a real figure — there is nothing to
        # redact here since it carries no personal information.
        session.add(
            Goal(
                user_id=user_id,
                key="emergency_fund",
                label="Emergency fund",
                target_minor=None,
                target_date=None,
                baseline_minor=0,
                baseline_date=now_london().strftime("%Y-%m-%d"),
                source_account_ids="[]",
            )
        )

    session.commit()
