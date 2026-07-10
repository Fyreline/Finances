"""routers/goals.py — docs/API.md §5 "Goals". Exercises the router's
snapshot-aggregation + `engines/goals.py` wiring end-to-end against manual
accounts (no need for real Starling/T212 fixtures here — that plumbing is
proven separately in test_sync_service*.py). Uses generic, non-personal
figures throughout (docs/PRIVATE.md's redaction scheme) — never the real
target/baseline/deadline.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Goal
from tests.conftest import auth_headers, make_user


def _seed_goal(user_id: int, **overrides) -> Goal:
    defaults = dict(
        user_id=user_id,
        key="house_deposit",
        label="House deposit",
        target_minor=1_000_000,
        target_date="2027-01-10",
        baseline_minor=100_000,
        baseline_date="2026-01-01",
        source_account_ids="[]",
    )
    defaults.update(overrides)
    with SessionLocal() as session:
        goal = Goal(**defaults)
        session.add(goal)
        session.commit()
        session.refresh(goal)
        return goal


def test_goals_requires_auth(client):
    res = client.get("/api/goals")
    assert res.status_code == 401


def test_goals_empty_before_seeding(client):
    user_id = make_user()
    res = client.get("/api/goals", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json() == {"goals": []}


def test_goal_with_no_snapshots_uses_baseline_as_current_and_renders_pinned_required(client):
    """The pinned worked-example shape (docs/DATA_MODEL.md §4a, generic
    placeholder figures): a goal with no source-account snapshots yet falls
    back to its baseline as the current balance, and required_per_month is
    still computed."""
    user_id = make_user()
    _seed_goal(user_id)

    res = client.get("/api/goals", headers=auth_headers(user_id))
    goal = res.json()["goals"][0]
    assert goal["current_minor"] == 100_000
    assert goal["required_per_month_minor"] == 150_000
    assert goal["status"] == "no_trend"
    assert goal["series"] == []


def test_goal_sums_source_accounts_and_renders_trend(client):
    user_id = make_user()
    a1 = client.post(
        "/api/accounts/manual",
        json={"name": "Pot", "kind": "savings", "balance_minor": 100_000},
        headers=auth_headers(user_id),
    ).json()["account"]["id"]

    for local_date, balance in [("2026-05-31", 100_000), ("2026-06-30", 190_000), ("2026-07-31", 280_000)]:
        client.post(
            f"/api/accounts/{a1}/balance",
            json={"balance_minor": balance, "local_date": local_date},
            headers=auth_headers(user_id),
        )

    _seed_goal(user_id, source_account_ids=f"[{a1}]", target_minor=None, target_date=None, key="t212_rebuild")

    res = client.get("/api/goals", headers=auth_headers(user_id))
    goal = res.json()["goals"][0]
    assert goal["current_minor"] == 280_000
    assert goal["trend_per_month_minor"] == 90_000
    assert goal["status"] == "no_trend"  # open-ended goal: trend shown, no verdict
    # >=3, not ==3: manual-account creation also drops today's own snapshot
    # into the series (the account's creation-day balance) alongside the
    # three explicit month-end points added above.
    series_dates = {point["date"] for point in goal["series"]}
    assert {"2026-05-31", "2026-06-30", "2026-07-31"} <= series_dates


def test_patch_goal_updates_monthly_pledge_and_target(client):
    user_id = make_user()
    _seed_goal(user_id)

    res = client.patch(
        "/api/goals/house_deposit",
        json={"monthly_pledge_minor": 50_000, "target_minor": 900_000},
        headers=auth_headers(user_id),
    )
    assert res.status_code == 200
    goal = res.json()["goal"]
    assert goal["target_minor"] == 900_000
    assert goal["monthly_pledge_minor"] == 50_000


def test_patch_goal_rejects_unknown_account_in_source_account_ids(client):
    user_id = make_user()
    _seed_goal(user_id)

    res = client.patch(
        "/api/goals/house_deposit",
        json={"source_account_ids": [999999]},
        headers=auth_headers(user_id),
    )
    assert res.status_code == 400


def test_patch_goal_404s_for_unknown_key(client):
    user_id = make_user()
    res = client.patch("/api/goals/not_a_real_goal", json={"target_minor": 100}, headers=auth_headers(user_id))
    assert res.status_code == 404


def test_patch_goal_empty_body_is_400(client):
    user_id = make_user()
    _seed_goal(user_id)
    res = client.patch("/api/goals/house_deposit", json={}, headers=auth_headers(user_id))
    assert res.status_code == 400


def test_goals_scoped_to_authenticated_user(client):
    owner_id = make_user(email="owner@example.com", mishka_id=1)
    other_id = make_user(email="other@example.com", mishka_id=2)
    _seed_goal(owner_id)

    res = client.get("/api/goals", headers=auth_headers(other_id))
    assert res.json() == {"goals": []}
