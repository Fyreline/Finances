"""routers/accounts.py — docs/API.md §5 "Accounts & balances". Manual
accounts are local-only DB writes, never a write to any bank/broker
(docs/PLAN.md §6 rule 6).
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import BalanceSnapshot
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
    assert res.json() == {"series": [], "as_of": None}


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
