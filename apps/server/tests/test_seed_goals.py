"""app/seed_goals.py — docs/phases/PHASE-3-t212-goals.md item 4. Every
config value used here is a generic, non-personal figure chosen to NOT
reconstruct the real target/baseline/dates (docs/PRIVATE.md's redaction
scheme) — those only ever live in a local gitignored `.env`, never in this
test file.
"""
from __future__ import annotations

from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.models import Goal
from app.seed_goals import seed_goals
from tests.conftest import make_user


def _settings(**overrides) -> Settings:
    defaults = dict(jwt_secret="test-secret")
    defaults.update(overrides)
    return Settings(**defaults)


def test_seed_goals_noop_without_a_user():
    with SessionLocal() as session:
        seed_goals(session, _settings())
        assert session.scalars(select(Goal)).all() == []


def test_seed_goals_creates_nothing_when_env_unset():
    user_id = make_user()
    with SessionLocal() as session:
        seed_goals(session, _settings(), user_id=user_id)
        goals = {g.key for g in session.scalars(select(Goal)).all()}
    # emergency_fund always seeds (a stub, no personal figures involved);
    # house_deposit/t212_rebuild need their env vars set first.
    assert goals == {"emergency_fund"}


def test_seed_goals_creates_t212_rebuild_when_baseline_configured():
    user_id = make_user()
    settings = _settings(goal_t212_rebuild_baseline_minor="45000", goal_t212_rebuild_baseline_date="2025-11-15")
    with SessionLocal() as session:
        seed_goals(session, settings, user_id=user_id)
        goal = session.scalar(select(Goal).where(Goal.key == "t212_rebuild"))
    assert goal is not None
    assert goal.target_minor is None
    assert goal.baseline_minor == 45_000
    assert goal.baseline_date == "2025-11-15"


def test_seed_goals_creates_house_deposit_and_defaults_its_baseline_to_t212s():
    user_id = make_user()
    settings = _settings(
        goal_t212_rebuild_baseline_minor="45000",
        goal_t212_rebuild_baseline_date="2025-11-15",
        goal_house_deposit_target_minor="833300",
        goal_house_deposit_target_date="2026-09-22",
    )
    with SessionLocal() as session:
        seed_goals(session, settings, user_id=user_id)
        goal = session.scalar(select(Goal).where(Goal.key == "house_deposit"))
    assert goal is not None
    assert goal.target_minor == 833_300
    assert goal.target_date == "2026-09-22"
    assert goal.baseline_minor == 45_000, "defaults to the T212 baseline when its own isn't set"
    assert goal.baseline_date == "2025-11-15"


def test_seed_goals_house_deposit_own_baseline_overrides_t212_default():
    user_id = make_user()
    settings = _settings(
        goal_t212_rebuild_baseline_minor="45000",
        goal_t212_rebuild_baseline_date="2025-11-15",
        goal_house_deposit_target_minor="833300",
        goal_house_deposit_target_date="2026-09-22",
        goal_house_deposit_baseline_minor="77000",
        goal_house_deposit_baseline_date="2026-02-03",
    )
    with SessionLocal() as session:
        seed_goals(session, settings, user_id=user_id)
        goal = session.scalar(select(Goal).where(Goal.key == "house_deposit"))
    assert goal.baseline_minor == 77_000
    assert goal.baseline_date == "2026-02-03"


def test_seed_goals_never_overwrites_an_existing_row():
    """A restart must not clobber a user's PATCHed target_minor with
    whatever the current `.env` happens to say (docs/phases/
    PHASE-3-t212-goals.md item 4 "never hardcode")."""
    user_id = make_user()
    settings = _settings(goal_t212_rebuild_baseline_minor="45000", goal_t212_rebuild_baseline_date="2025-11-15")
    with SessionLocal() as session:
        seed_goals(session, settings, user_id=user_id)
        goal = session.scalar(select(Goal).where(Goal.key == "t212_rebuild"))
        goal.baseline_minor = 11_111
        session.commit()

    with SessionLocal() as session:
        seed_goals(session, settings, user_id=user_id)
        goal = session.scalar(select(Goal).where(Goal.key == "t212_rebuild"))
    assert goal.baseline_minor == 11_111, "the second seed_goals call must leave the edited row alone"


def test_seed_goals_emergency_fund_is_a_stub():
    user_id = make_user()
    with SessionLocal() as session:
        seed_goals(session, _settings(), user_id=user_id)
        goal = session.scalar(select(Goal).where(Goal.key == "emergency_fund"))
    assert goal.target_minor is None
    assert goal.baseline_minor == 0
