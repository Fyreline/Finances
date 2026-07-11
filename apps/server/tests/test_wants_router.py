"""routers/wants.py — docs/PLAN.md §3 row 11 (refined), docs/phases/
PHASE-9-personal-goals.md §5. Every label/price is a clearly synthetic
placeholder (docs/PRIVATE.md).
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Account, BalanceSnapshot, Goal
from tests.conftest import auth_headers, make_user


def test_wants_requires_auth(client):
    assert client.get("/api/wants").status_code == 401


def test_wants_empty_before_any_created(client):
    user_id = make_user()
    res = client.get("/api/wants", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json() == {"wants": []}


def test_create_want_with_no_setup_yet_is_unknown_affordability(client):
    """Fresh-setup state: no safe-to-spend config, no house_deposit goal —
    the affordability check degrades honestly rather than crashing or
    guessing (docs/phases/PHASE-9 acceptance list)."""
    user_id = make_user()
    res = client.post("/api/wants", headers=auth_headers(user_id), json={"label": "widget", "price_minor": 5_000})
    assert res.status_code == 201
    want = res.json()["want"]
    assert want["affordability"]["verdict"] == "unknown"


def test_want_fits_now_within_safe_to_spend_headroom(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    client.put(
        "/api/financial-config",
        headers=headers,
        json={"payday_day": 28, "net_monthly_income_minor": 250_000, "buffer_minor": 15_000},
    )
    res = client.post("/api/wants", headers=headers, json={"label": "widget", "price_minor": 5_000})
    assert res.json()["want"]["affordability"]["verdict"] == "fits_now"


def test_want_not_yet_when_it_would_meaningfully_delay_the_house_deposit(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    client.put(
        "/api/financial-config",
        headers=headers,
        json={"payday_day": 28, "net_monthly_income_minor": 100_000, "buffer_minor": 90_000},
    )
    with SessionLocal() as session:
        account = Account(user_id=user_id, provider="manual", name="Test savings", kind="savings", currency="GBP")
        session.add(account)
        session.commit()
        session.refresh(account)
        for local_date, balance in (("2026-05-31", 100_000), ("2026-06-30", 190_000), ("2026-07-10", 280_000)):
            session.add(
                BalanceSnapshot(
                    account_id=account.id, captured_at=f"{local_date} 00:00:00", local_date=local_date, balance_minor=balance
                )
            )
        session.add(
            Goal(
                user_id=user_id,
                key="house_deposit",
                label="House deposit",
                target_minor=2_000_000,
                target_date="2027-01-10",
                baseline_minor=100_000,
                baseline_date="2026-05-31",
                source_account_ids=f"[{account.id}]",
            )
        )
        session.commit()

    # Nearly no safe-to-spend headroom this period, and a price big enough to
    # come out of savings and meaningfully push a behind-target goal further back.
    res = client.post("/api/wants", headers=headers, json={"label": "widget", "price_minor": 500_000})
    affordability = res.json()["want"]["affordability"]
    assert affordability["verdict"] == "not_yet"
    assert "week" in affordability["detail"]


def test_bought_want_has_no_live_affordability_verdict(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    want_id = client.post("/api/wants", headers=headers, json={"label": "widget", "price_minor": 5_000}).json()["want"]["id"]
    patched = client.patch(f"/api/wants/{want_id}", headers=headers, json={"bought": True}).json()["want"]
    assert patched["bought"] is True
    assert patched["affordability"] is None


def test_want_delete_and_404_for_another_users_want(client):
    owner = make_user(email="owner@example.com", mishka_id=1)
    intruder = make_user(email="intruder@example.com", mishka_id=2)
    want_id = client.post("/api/wants", headers=auth_headers(owner), json={"label": "widget", "price_minor": 1_000}).json()["want"]["id"]

    assert client.patch(f"/api/wants/{want_id}", headers=auth_headers(intruder), json={"bought": True}).status_code == 404
    assert client.delete(f"/api/wants/{want_id}", headers=auth_headers(intruder)).status_code == 404

    assert client.delete(f"/api/wants/{want_id}", headers=auth_headers(owner)).status_code == 200
    assert client.get("/api/wants", headers=auth_headers(owner)).json() == {"wants": []}


def test_non_positive_price_rejected(client):
    user_id = make_user()
    headers = auth_headers(user_id)
    assert client.post("/api/wants", headers=headers, json={"label": "widget", "price_minor": 0}).status_code == 400
    want_id = client.post("/api/wants", headers=headers, json={"label": "widget", "price_minor": 1_000}).json()["want"]["id"]
    assert client.patch(f"/api/wants/{want_id}", headers=headers, json={"price_minor": -1}).status_code == 400
