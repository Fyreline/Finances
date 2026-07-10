"""Tax router — app/routers/tax.py, docs/API.md §5, docs/TAX.md.

Covers the null-until-answered estimate contract, the disclaimer on every
response, the mortgage-interest/capital exclusions, the unreviewed-document
gate into the ledger, the CSV export, and the is_rental candidates.
"""
from __future__ import annotations

from app.db import SessionLocal
from app.models import Account, TaxDocument, Transaction

from tests.conftest import auth_headers, make_user  # noqa: F401  (imported for parity/use)


def _put_config(client, headers, **fields) -> dict:
    return client.put("/api/tax/config", json=fields, headers=headers).json()


def _add_ledger(client, headers, **body):
    return client.post("/api/tax/ledger", json=body, headers=headers)


# --------------------------------------------------------------------------- #
#  Config                                                                       #
# --------------------------------------------------------------------------- #
def test_config_starts_null_with_field_help(authed):
    client, _uid, headers = authed
    body = client.get("/api/tax/config", headers=headers).json()["config"]
    assert body["has_mortgage"] is None
    assert body["employment_gross_annual_minor"] is None
    # Every open question is explained (docs/TAX.md §2 → the setup form).
    assert "has_mortgage" in body["field_help"] and "Section 24" in body["field_help"]["has_mortgage"]


def test_config_rejects_invalid_flag(authed):
    client, _uid, headers = authed
    res = client.put("/api/tax/config", json={"has_mortgage": 2}, headers=headers)
    assert res.status_code == 400 and res.json()["code"] == "invalid_flag"


# --------------------------------------------------------------------------- #
#  Estimate: null until answered, then computed (docs/TAX.md §0)                #
# --------------------------------------------------------------------------- #
def test_summary_null_with_missing_inputs_but_always_has_disclaimer(authed):
    client, _uid, headers = authed
    body = client.get("/api/tax/years/2026-27/summary", headers=headers).json()
    assert body["estimate"] is None
    assert body["missing_inputs"] == ["has_mortgage", "employment_gross_annual"]
    # Load-bearing: the disclaimer is present even when the estimate is null.
    assert "planning only" in body["disclaimer"]


def test_summary_computes_worked_example_and_excludes_mortgage_and_capital(authed):
    client, _uid, headers = authed
    _put_config(
        client,
        headers,
        has_mortgage=1,
        annual_mortgage_interest_minor=360_000,  # £3,600
        employment_gross_annual_minor=4_800_000,  # £48,000
    )
    # docs/TAX.md §5d worked example 1 income + expenses, all in 2026-27.
    _add_ledger(client, headers, local_date="2026-06-01", kind="income", amount_minor=1_020_000)
    _add_ledger(client, headers, local_date="2026-06-02", kind="expense", expense_type="agent_fees", amount_minor=102_000)
    _add_ledger(client, headers, local_date="2026-06-03", kind="expense", expense_type="insurance", amount_minor=24_000)
    _add_ledger(client, headers, local_date="2026-06-04", kind="expense", expense_type="repairs", amount_minor=60_000)
    # A mortgage_interest ledger row (tracked, excluded from allowable) and a
    # capital_improvement row (excluded from everything) — docs/TAX.md §4.
    _add_ledger(client, headers, local_date="2026-06-05", kind="expense", expense_type="mortgage_interest", amount_minor=360_000)
    _add_ledger(client, headers, local_date="2026-06-06", kind="expense", expense_type="capital_improvement", amount_minor=500_000)

    body = client.get("/api/tax/years/2026-27/summary", headers=headers).json()
    assert body["missing_inputs"] == []
    # Allowable total excludes mortgage_interest and capital_improvement.
    assert body["allowable_total_minor"] == 186_000
    assert "mortgage_interest" not in body["allowable_expenses"]
    assert "capital_improvement" not in body["allowable_expenses"]
    est = body["estimate"]
    assert est["method_used"] == "expenses_plus_s24"
    assert est["tax_due_minor"] == 278_280
    assert est["s24_credit_minor"] == 72_000
    assert est["nic_due_minor"] == 0
    assert est["disclaimer"]
    # 2026-27 rates are not entered yet → a visible assumption, never silent.
    assert any("2026-27" in a for a in est["assumptions"])


def test_ground_rent_only_allowable_when_leasehold(authed):
    client, _uid, headers = authed
    _put_config(client, headers, has_mortgage=0, employment_gross_annual_minor=4_800_000, is_leasehold=0)
    _add_ledger(client, headers, local_date="2026-06-01", kind="income", amount_minor=1_020_000)
    _add_ledger(client, headers, local_date="2026-06-02", kind="expense", expense_type="ground_rent_service", amount_minor=12_000)

    body = client.get("/api/tax/years/2026-27/summary", headers=headers).json()
    assert "ground_rent_service" not in body["allowable_expenses"]  # not leasehold → excluded

    _put_config(client, headers, is_leasehold=1)
    body2 = client.get("/api/tax/years/2026-27/summary", headers=headers).json()
    assert body2["allowable_expenses"]["ground_rent_service"] == 12_000  # leasehold → allowable


# --------------------------------------------------------------------------- #
#  Documents & the unreviewed-document gate (docs/API.md §3c)                   #
# --------------------------------------------------------------------------- #
def _insert_document(reviewed: int) -> int:
    with SessionLocal() as session:
        doc = TaxDocument(
            tax_year="2026-27",
            source="gmail",
            gmail_message_id=f"msg-{reviewed}-x",
            doc_type="rent_statement",
            received_at="2026-06-01",
            file_path="tax-documents/2026-27/x",
            amount_minor=85_000,
            amount_confidence="parsed",
            reviewed=reviewed,
        )
        session.add(doc)
        session.commit()
        return doc.id


def test_ledger_rejects_link_to_unreviewed_document(authed):
    client, _uid, headers = authed
    doc_id = _insert_document(reviewed=0)
    res = _add_ledger(
        client, headers, local_date="2026-06-01", kind="income", amount_minor=85_000, tax_document_id=doc_id
    )
    assert res.status_code == 400 and res.json()["code"] == "document_unreviewed"

    # Review it, then the link is accepted.
    client.patch(f"/api/tax/documents/{doc_id}", json={"reviewed": 1}, headers=headers)
    ok = _add_ledger(
        client, headers, local_date="2026-06-01", kind="income", amount_minor=85_000, tax_document_id=doc_id
    )
    assert ok.status_code == 201


def test_documents_unreviewed_filter(authed):
    client, _uid, headers = authed
    _insert_document(reviewed=0)
    _insert_document(reviewed=1)
    unreviewed = client.get("/api/tax/documents?unreviewed=1", headers=headers).json()["documents"]
    assert len(unreviewed) == 1 and unreviewed[0]["reviewed"] is False


# --------------------------------------------------------------------------- #
#  Ledger CRUD, CSV, candidates                                                #
# --------------------------------------------------------------------------- #
def test_ledger_validation_and_csv_export(authed):
    client, _uid, headers = authed
    # Expense row without a valid type is rejected.
    bad = _add_ledger(client, headers, local_date="2026-06-01", kind="expense", amount_minor=1000)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_expense_type"

    _add_ledger(client, headers, local_date="2026-06-01", kind="income", amount_minor=85_000)
    _add_ledger(client, headers, local_date="2026-06-02", kind="expense", expense_type="repairs", amount_minor=60_000)

    csv_res = client.get("/api/tax/ledger?year=2026-27&format=csv", headers=headers)
    assert csv_res.status_code == 200 and csv_res.headers["content-type"].startswith("text/csv")
    text = csv_res.text
    assert "amount_gbp" in text and "850.00" in text and "600.00" in text


def test_delete_ledger_entry(authed):
    client, _uid, headers = authed
    created = _add_ledger(client, headers, local_date="2026-06-01", kind="income", amount_minor=85_000).json()["entry"]
    res = client.delete(f"/api/tax/ledger/{created['id']}", headers=headers)
    assert res.status_code == 200 and res.json()["deleted"] is True


def test_rental_candidates_from_is_rental_transactions(authed):
    client, uid, headers = authed
    with SessionLocal() as session:
        acc = Account(user_id=uid, provider="starling", provider_account_uid="acc-x", name="Starling", kind="current")
        session.add(acc)
        session.commit()
        session.refresh(acc)
        session.add(
            Transaction(
                account_id=acc.id,
                provider_uid="feed-1",
                amount_minor=85_000,
                transaction_time="2026-06-01T09:00:00.000Z",
                local_date="2026-06-01",
                is_rental=1,
                raw_json="{}",
            )
        )
        session.commit()

    cands = client.get("/api/tax/candidates?year=2026-27", headers=headers).json()["candidates"]
    assert len(cands) == 1
    assert cands[0]["suggested_kind"] == "income" and cands[0]["tax_year"] == "2026-27"
