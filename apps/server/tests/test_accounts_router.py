"""routers/accounts.py — docs/API.md §5 "Accounts & balances". Manual
accounts are local-only DB writes, never a write to any bank/broker
(docs/PLAN.md §6 rule 6).
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Account, BalanceSnapshot, Category, Transaction
from tests.conftest import auth_headers, make_user


def test_accounts_requires_auth(client):
    res = client.get("/api/accounts")
    assert res.status_code == 401


def test_accounts_empty_before_any_sync_or_manual_entry(client):
    user_id = make_user()
    res = client.get("/api/accounts", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json() == {"accounts": []}


def test_create_manual_account_and_read_it_back(client):
    user_id = make_user()
    res = client.post(
        "/api/accounts/manual",
        json={"name": "Cash ISA elsewhere", "kind": "savings", "balance_minor": 50000},
        headers=auth_headers(user_id),
    )
    assert res.status_code == 201
    account_id = res.json()["account"]["id"]

    listed = client.get("/api/accounts", headers=auth_headers(user_id)).json()["accounts"]
    assert len(listed) == 1
    assert listed[0]["id"] == account_id
    assert listed[0]["provider"] == "manual"
    assert listed[0]["latest_balance_minor"] == 50000
    assert listed[0]["status"] == "ok"

    with SessionLocal() as session:
        snaps = session.query(BalanceSnapshot).filter_by(account_id=account_id).all()
        assert len(snaps) == 1
        assert snaps[0].balance_minor == 50000


def test_manual_balance_entry_upserts_same_day(client):
    user_id = make_user()
    create = client.post(
        "/api/accounts/manual",
        json={"name": "Cash ISA elsewhere", "kind": "savings", "balance_minor": 50000},
        headers=auth_headers(user_id),
    )
    account_id = create.json()["account"]["id"]

    res1 = client.post(
        f"/api/accounts/{account_id}/balance",
        json={"balance_minor": 60000, "local_date": "2026-08-01"},
        headers=auth_headers(user_id),
    )
    assert res1.status_code == 200
    res2 = client.post(
        f"/api/accounts/{account_id}/balance",
        json={"balance_minor": 61000, "local_date": "2026-08-01"},
        headers=auth_headers(user_id),
    )
    assert res2.status_code == 200

    with SessionLocal() as session:
        snaps = session.query(BalanceSnapshot).filter_by(account_id=account_id, local_date="2026-08-01").all()
        assert len(snaps) == 1, "same local_date -> updated in place, not duplicated"
        assert snaps[0].balance_minor == 61000


def test_manual_balance_entry_404s_for_unknown_account(client):
    user_id = make_user()
    res = client.post(
        "/api/accounts/999999/balance",
        json={"balance_minor": 100, "local_date": "2026-08-01"},
        headers=auth_headers(user_id),
    )
    assert res.status_code == 404


def test_manual_balance_entry_404s_for_another_users_account(client):
    owner_id = make_user(email="owner@example.com", mishka_id=1)
    intruder_id = make_user(email="intruder@example.com", mishka_id=2)
    create = client.post(
        "/api/accounts/manual",
        json={"name": "Owner's account", "kind": "savings", "balance_minor": 1000},
        headers=auth_headers(owner_id),
    )
    account_id = create.json()["account"]["id"]

    res = client.post(
        f"/api/accounts/{account_id}/balance",
        json={"balance_minor": 999999, "local_date": "2026-08-01"},
        headers=auth_headers(intruder_id),
    )
    assert res.status_code == 404


def test_networth_empty_with_no_accounts(client):
    user_id = make_user()
    res = client.get("/api/networth", headers=auth_headers(user_id))
    assert res.status_code == 200
    body = res.json()
    assert body["total_minor"] == 0
    assert body["by_account"] == []
    assert body["series"] == []
    assert body["as_of"] is None
    # S2/S4 (docs/phases/PHASE-9-personal-goals.md) degrade honestly too —
    # no essential-spend history yet, no pension answer yet.
    assert body["emergency_fund"] == {
        "months_of_cover": None,
        "verdict": "unknown",
        "copy": "Not enough spending history yet to estimate essential monthly costs.",
    }
    assert body["contractor_gap"] == {
        "pension_contributing": None,
        "fte_conversion_target_date": None,
        "fte_runway_goal": None,
    }


def test_networth_sums_across_manual_accounts_by_date(client):
    user_id = make_user()
    a1 = client.post(
        "/api/accounts/manual",
        json={"name": "Account 1", "kind": "current", "balance_minor": 1000},
        headers=auth_headers(user_id),
    ).json()["account"]["id"]
    a2 = client.post(
        "/api/accounts/manual",
        json={"name": "Account 2", "kind": "savings", "balance_minor": 2000},
        headers=auth_headers(user_id),
    ).json()["account"]["id"]

    # A second day of snapshots for both accounts, via the manual-balance
    # endpoint — proves the carry-forward sum lines dates up correctly
    # across accounts, not just the initial same-day creation snapshots.
    client.post(
        f"/api/accounts/{a1}/balance",
        json={"balance_minor": 1500, "local_date": "2026-08-02"},
        headers=auth_headers(user_id),
    )
    client.post(
        f"/api/accounts/{a2}/balance",
        json={"balance_minor": 2500, "local_date": "2026-08-02"},
        headers=auth_headers(user_id),
    )

    res = client.get("/api/networth", headers=auth_headers(user_id))
    body = res.json()
    assert body["as_of"] is not None
    totals = {point["date"]: point["total_minor"] for point in body["series"]}
    assert totals["2026-08-02"] == 4000
    # The "now" figures reflect the latest date across both accounts.
    assert body["total_minor"] == 4000
    by_account = {row["name"]: row["balance_minor"] for row in body["by_account"]}
    assert by_account == {"Account 1": 1500, "Account 2": 2500}


# ------------------------------------------------------- S2 emergency fund
def test_networth_emergency_fund_uses_real_accessible_cash_and_essential_spend(client):
    """docs/PLAN.md §4 S2, docs/phases/PHASE-9-personal-goals.md §2 —
    end-to-end: a savings balance + three months of a fixed-category spend
    (synthetic figures, docs/PRIVATE.md) produces a real months-of-cover
    verdict, and an investment-kind account is correctly excluded from
    "accessible cash" (S2's accessible_cash excludes T212)."""
    user_id = make_user()
    headers = auth_headers(user_id)
    with SessionLocal() as session:
        savings = Account(user_id=user_id, provider="manual", name="Savings", kind="savings", currency="GBP")
        investment = Account(user_id=user_id, provider="manual", name="ISA", kind="investment", currency="GBP")
        session.add_all([savings, investment])
        session.commit()
        session.refresh(savings)
        session.refresh(investment)
        session.add_all(
            [
                BalanceSnapshot(account_id=savings.id, captured_at="2026-07-01 00:00:00", local_date="2026-07-01", balance_minor=150_000),
                BalanceSnapshot(account_id=investment.id, captured_at="2026-07-01 00:00:00", local_date="2026-07-01", balance_minor=999_999),
            ]
        )
        housing = session.query(Category).filter_by(key="housing").one()
        for i, month in enumerate(("2026-05", "2026-06", "2026-07")):
            session.add(
                Transaction(
                    account_id=savings.id,
                    provider_uid=f"rent-{i}",
                    amount_minor=-50_000,
                    transaction_time=f"{month}-01T00:00:00Z",
                    local_date=f"{month}-01",
                    settled=1,
                    counterparty="Landlord",
                    category_id=housing.id,
                    category_source="provider",
                    raw_json="{}",
                )
            )
        session.commit()

    body = client.get("/api/networth", headers=headers).json()
    # accessible cash = savings only (£1,500), essential = £500/month avg -> 3.0 months exactly
    assert body["emergency_fund"]["months_of_cover"] == 3.0
    assert body["emergency_fund"]["verdict"] == "within_range"
    # Net worth itself, by contrast, includes every include_in_networth
    # account (both savings and the investment).
    assert body["total_minor"] == 150_000 + 999_999


# ------------------------------------------------------------ S4 contractor gap
def test_networth_contractor_gap_reflects_config_and_fte_runway_goal(client):
    user_id = make_user()
    headers = auth_headers(user_id)

    before = client.get("/api/networth", headers=headers).json()["contractor_gap"]
    assert before == {"pension_contributing": None, "fte_conversion_target_date": None, "fte_runway_goal": None}

    client.put(
        "/api/financial-config",
        headers=headers,
        json={"pension_contributing": False, "fte_conversion_target_date": "2028-04-01"},
    )
    after = client.get("/api/networth", headers=headers).json()["contractor_gap"]
    assert after["pension_contributing"] is False
    assert after["fte_conversion_target_date"] == "2028-04-01"
    assert after["fte_runway_goal"]["key"] == "fte_runway"
    assert after["fte_runway_goal"]["target_minor"] is None
