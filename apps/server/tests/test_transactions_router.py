"""routers/transactions.py — transactions list/patch, categories, rules
CRUD + retro-apply (docs/API.md §5). Seeds rows directly via SessionLocal
(no live Starling call needed — that's test_sync_service.py's job) so this
file stays focused on the HTTP contract.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Category, Transaction
from tests.conftest import auth_headers, make_user


def _seed_account(user_id: int) -> int:
    with SessionLocal() as session:
        account = Account(
            user_id=user_id,
            provider="starling",
            provider_account_uid=f"acc-router-test-{user_id}",
            name="Personal",
            kind="current",
            currency="GBP",
            default_category_uid="cat-router-test",
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return account.id


def _category_id(key: str) -> int:
    with SessionLocal() as session:
        return session.scalar(select(Category).where(Category.key == key)).id


def _seed_transaction(
    account_id: int,
    provider_uid: str,
    *,
    amount_minor: int,
    local_date: str,
    counterparty: str,
    reference: str = "",
    category_key: str | None = None,
    category_source: str = "provider",
) -> int:
    with SessionLocal() as session:
        category_id = None
        if category_key:
            category_id = session.scalar(select(Category).where(Category.key == category_key)).id
        txn = Transaction(
            account_id=account_id,
            provider_uid=provider_uid,
            amount_minor=amount_minor,
            transaction_time=f"{local_date}T12:00:00.000Z",
            local_date=local_date,
            settled=1,
            counterparty=counterparty,
            reference=reference,
            provider_category="GROCERIES",
            category_id=category_id,
            category_source=category_source,
            raw_json="{}",
        )
        session.add(txn)
        session.commit()
        session.refresh(txn)
        return txn.id


# --------------------------------------------------------------- list/filter
def test_list_transactions_requires_auth(client):
    res = client.get("/api/transactions")
    assert res.status_code == 401


def test_list_transactions_returns_only_the_authed_users_rows(client):
    user_id = make_user()
    other_user_id = make_user(email="other@example.com", mishka_id=2)
    my_account = _seed_account(user_id)
    other_account = _seed_account(other_user_id)
    _seed_transaction(my_account, "mine-1", amount_minor=-500, local_date="2026-07-01", counterparty="Willow & Pine Grocers")
    _seed_transaction(other_account, "theirs-1", amount_minor=-999, local_date="2026-07-01", counterparty="Someone Else")

    res = client.get("/api/transactions", headers=auth_headers(user_id))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["counterparty"] == "Willow & Pine Grocers"
    assert body["page_size"] == 50


def test_list_transactions_filters_by_month_category_and_search(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    _seed_transaction(
        account_id, "t1", amount_minor=-4599, local_date="2026-07-05",
        counterparty="Willow & Pine Grocers", reference="GROCERY SHOP", category_key="groceries",
    )
    _seed_transaction(
        account_id, "t2", amount_minor=-999, local_date="2026-07-12",
        counterparty="Streamly Plus", reference="SUBSCRIPTION", category_key="subscriptions",
    )
    _seed_transaction(
        account_id, "t3", amount_minor=-1500, local_date="2026-06-20",
        counterparty="Willow & Pine Grocers", reference="GROCERY SHOP", category_key="groceries",
    )

    res = client.get("/api/transactions", params={"month": "2026-07"}, headers=auth_headers(user_id))
    assert res.json()["total"] == 2

    res = client.get(
        "/api/transactions", params={"month": "2026-07", "category": "groceries"}, headers=auth_headers(user_id)
    )
    assert res.json()["total"] == 1

    res = client.get("/api/transactions", params={"q": "streamly"}, headers=auth_headers(user_id))
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["counterparty"] == "Streamly Plus"


def test_amount_minor_is_signed_and_untouched_by_the_api(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    _seed_transaction(account_id, "signed-1", amount_minor=-4599, local_date="2026-07-01", counterparty="Willow & Pine Grocers")
    _seed_transaction(account_id, "signed-2", amount_minor=250000, local_date="2026-07-02", counterparty="Bluebell Consulting Ltd")

    res = client.get("/api/transactions", headers=auth_headers(user_id))
    amounts = {item["counterparty"]: item["amount_minor"] for item in res.json()["items"]}
    assert amounts["Willow & Pine Grocers"] == -4599
    assert amounts["Bluebell Consulting Ltd"] == 250000


def test_pagination_page_size_is_fifty(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    for i in range(60):
        _seed_transaction(account_id, f"page-{i}", amount_minor=-100, local_date="2026-07-01", counterparty=f"Merchant {i}")

    res = client.get("/api/transactions", params={"page": 1}, headers=auth_headers(user_id))
    body = res.json()
    assert body["total"] == 60
    assert len(body["items"]) == 50

    res = client.get("/api/transactions", params={"page": 2}, headers=auth_headers(user_id))
    assert len(res.json()["items"]) == 10


# ------------------------------------------------------------------- patch
def test_patch_transaction_sets_manual_source(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    txn_id = _seed_transaction(account_id, "patch-1", amount_minor=-999, local_date="2026-07-01", counterparty="Streamly Plus", category_key="fun")
    new_category_id = _category_id("subscriptions")

    res = client.patch(f"/api/transactions/{txn_id}", json={"category_id": new_category_id}, headers=auth_headers(user_id))
    assert res.status_code == 200
    body = res.json()["transaction"]
    assert body["category"]["key"] == "subscriptions"
    assert body["category_source"] == "manual"


def test_patch_transaction_not_found_for_other_users_row(client):
    user_id = make_user()
    other_user_id = make_user(email="other2@example.com", mishka_id=3)
    other_account = _seed_account(other_user_id)
    txn_id = _seed_transaction(other_account, "not-mine", amount_minor=-100, local_date="2026-07-01", counterparty="X")

    res = client.patch(f"/api/transactions/{txn_id}", json={"is_rental": True}, headers=auth_headers(user_id))
    assert res.status_code == 404


def test_patch_transaction_empty_body_rejected(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    txn_id = _seed_transaction(account_id, "empty-patch", amount_minor=-100, local_date="2026-07-01", counterparty="X")

    res = client.patch(f"/api/transactions/{txn_id}", json={}, headers=auth_headers(user_id))
    assert res.status_code == 400


def test_patch_transaction_unknown_category_rejected(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    txn_id = _seed_transaction(account_id, "bad-cat", amount_minor=-100, local_date="2026-07-01", counterparty="X")

    res = client.patch(f"/api/transactions/{txn_id}", json={"category_id": 999999}, headers=auth_headers(user_id))
    assert res.status_code == 400


# ---------------------------------------------------------------- categories
def test_list_categories_includes_full_seeded_taxonomy(client):
    user_id = make_user()
    res = client.get("/api/categories", headers=auth_headers(user_id))
    assert res.status_code == 200
    keys = {c["key"] for c in res.json()["categories"]}
    assert "groceries" in keys
    assert "salary" in keys


# --------------------------------------------------------------------- rules
def test_create_list_patch_delete_rule(client):
    user_id = make_user()
    category_id = _category_id("subscriptions")

    res = client.post(
        "/api/rules",
        json={"priority": 10, "match_field": "counterparty", "pattern": "streamly", "category_id": category_id},
        headers=auth_headers(user_id),
    )
    assert res.status_code == 201
    rule_id = res.json()["rule"]["id"]

    res = client.get("/api/rules", headers=auth_headers(user_id))
    assert len(res.json()["rules"]) == 1

    res = client.patch(f"/api/rules/{rule_id}", json={"priority": 5}, headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json()["rule"]["priority"] == 5

    res = client.delete(f"/api/rules/{rule_id}", headers=auth_headers(user_id))
    assert res.status_code == 200
    res = client.get("/api/rules", headers=auth_headers(user_id))
    assert res.json()["rules"] == []


def test_create_rule_rejects_unknown_match_field(client):
    user_id = make_user()
    category_id = _category_id("subscriptions")
    res = client.post(
        "/api/rules",
        json={"priority": 10, "match_field": "not_a_field", "pattern": "x", "category_id": category_id},
        headers=auth_headers(user_id),
    )
    assert res.status_code == 400


def test_apply_rule_retro_categorises_but_never_touches_manual_rows(client):
    user_id = make_user()
    account_id = _seed_account(user_id)
    auto_txn = _seed_transaction(
        account_id, "retro-1", amount_minor=-999, local_date="2026-07-01",
        counterparty="Streamly Plus", category_key="fun", category_source="provider",
    )
    manual_txn = _seed_transaction(
        account_id, "retro-2", amount_minor=-999, local_date="2026-07-02",
        counterparty="Streamly Plus", category_key="fun", category_source="manual",
    )
    subs_id = _category_id("subscriptions")

    res = client.post(
        "/api/rules",
        json={"priority": 1, "match_field": "counterparty", "pattern": "streamly", "category_id": subs_id},
        headers=auth_headers(user_id),
    )
    rule_id = res.json()["rule"]["id"]

    res = client.post(f"/api/rules/{rule_id}/apply", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json()["recategorised"] == 1

    with SessionLocal() as session:
        auto = session.get(Transaction, auto_txn)
        manual = session.get(Transaction, manual_txn)
    assert auto.category_id == subs_id
    assert auto.category_source == "rule"
    assert manual.category_source == "manual", "manual row must never be touched by retro-apply"
    assert manual.category_id == _category_id("fun")
