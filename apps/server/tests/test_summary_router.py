"""routers/summary.py + routers/recurring.py — the HTTP contract for
safe-to-spend (§6a), monthly breakdown (§6b), tips (§6c), recurring (§5), and
the financial-config form. Seeds rows directly; all figures synthetic.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Category, RecurringPayment, Transaction
from tests.conftest import auth_headers, make_user


def _seed_account(user_id: int) -> int:
    with SessionLocal() as session:
        account = Account(
            user_id=user_id,
            provider="starling",
            provider_account_uid=f"acc-summary-{user_id}",
            name="Personal",
            kind="current",
            currency="GBP",
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return account.id


def _seed_txn(account_id: int, uid: str, *, amount_minor: int, local_date: str, counterparty: str, category_key: str | None):
    with SessionLocal() as session:
        category_id = None
        if category_key:
            category_id = session.scalar(select(Category).where(Category.key == category_key)).id
        session.add(
            Transaction(
                account_id=account_id,
                provider_uid=uid,
                amount_minor=amount_minor,
                transaction_time=f"{local_date}T12:00:00.000Z",
                local_date=local_date,
                settled=1,
                counterparty=counterparty,
                reference="",
                provider_category=None,
                category_id=category_id,
                category_source="provider",
                raw_json="{}",
            )
        )
        session.commit()


# ------------------------------------------------------------ financial config
def test_financial_config_round_trip_and_validation(authed):
    client, user_id, headers = authed
    # defaults exist on first GET
    got = client.get("/api/financial-config", headers=headers).json()["financial_config"]
    assert got["payday_day"] is None
    assert got["buffer_minor"] == 15000

    bad = client.put("/api/financial-config", headers=headers, json={"payday_day": 40})
    assert bad.status_code == 400

    put = client.put(
        "/api/financial-config",
        headers=headers,
        json={"payday_day": 28, "net_monthly_income_minor": 250000, "flat_share_minor": 60000},
    )
    assert put.status_code == 200
    assert put.json()["financial_config"]["payday_day"] == 28


# ---------------------------------------------------------------- safe-to-spend
def test_safe_to_spend_setup_missing_then_live(authed):
    client, user_id, headers = authed
    setup = client.get("/api/summary/safe-to-spend", headers=headers).json()
    assert setup["safe_to_spend_minor"] is None
    assert "payday_day" in setup["setup_missing"]

    client.put(
        "/api/financial-config",
        headers=headers,
        json={"payday_day": 28, "net_monthly_income_minor": 250000, "flat_share_minor": 60000, "buffer_minor": 15000},
    )
    live = client.get("/api/summary/safe-to-spend", headers=headers).json()
    assert live["setup_missing"] == []
    # waterfall segments sum pence-exact to income (acceptance)
    segments = (
        live["committed_minor"]
        + live["goal_set_aside_minor"]
        + live["tax_set_aside_minor"]
        + live["buffer_minor"]
        + live["spent_so_far_minor"]
        + live["remaining_minor"]
    )
    assert segments == live["income_minor"] == 250000
    assert live["period"]["start"] and live["period"]["end"]


def test_safe_to_spend_tax_setaside_uses_live_estimate(authed):
    """Cross-phase seam (found in Phase 8): once the tax estimator's inputs are
    answered, 'auto' mode must set aside ceil(estimate ÷ months to next 31 Jan)
    — Phase 5's figure genuinely flowing into Phase 4's formula (docs/API.md
    §6a; PLAN §4 S5), not the hardcoded None it shipped with."""
    from app.dates import now_london, tax_year_of
    from app.engines.insights import months_to_next_31_jan

    client, user_id, headers = authed
    client.put(
        "/api/financial-config",
        headers=headers,
        json={"payday_day": 28, "net_monthly_income_minor": 250000},
    )
    # Answer the estimator's open questions (synthetic figures, TAX.md §5d).
    client.put(
        "/api/tax/config",
        headers=headers,
        json={"has_mortgage": 0, "employment_gross_annual_minor": 4_800_000},
    )
    today = now_london().date().isoformat()
    client.post(
        "/api/tax/ledger",
        headers=headers,
        json={"local_date": today, "kind": "income", "amount_minor": 1_020_000},
    )
    est = client.get(f"/api/tax/years/{tax_year_of(today)}/summary", headers=headers).json()["estimate"]
    assert est is not None and est["tax_due_minor"] > 0

    live = client.get("/api/summary/safe-to-spend", headers=headers).json()
    expected = -(-est["tax_due_minor"] // months_to_next_31_jan(today))  # ceil division
    assert live["tax_set_aside_minor"] == expected > 0
    # The waterfall still sums pence-exact to income with the new segment live.
    segments = (
        live["committed_minor"]
        + live["goal_set_aside_minor"]
        + live["tax_set_aside_minor"]
        + live["buffer_minor"]
        + live["spent_so_far_minor"]
        + live["remaining_minor"]
    )
    assert segments == live["income_minor"]


# ---------------------------------------------------------------- month summary
def test_month_summary_verdict_pill_kraft_not_crimson(authed):
    """A category ~25% over its band → above_average, not severe (kraft, not
    crimson), with band bounds + source date in the benchmark (acceptance)."""
    client, user_id, headers = authed
    account_id = _seed_account(user_id)
    # eating_out average_max is £220; ~£275/mo across 3 months = 25% over
    for i, month in enumerate(("2026-05", "2026-06", "2026-07")):
        _seed_txn(account_id, f"eo-{i}", amount_minor=-27500, local_date=f"{month}-10", counterparty="Dishoom", category_key="eating_out")

    summary = client.get("/api/summary/month/2026-07", headers=headers).json()
    eo = next(c for c in summary["categories"] if c["key"] == "eating_out")
    assert eo["benchmark"]["band"] == "above_average"
    assert eo["benchmark"]["severe"] is False
    assert eo["benchmark"]["band_bounds_minor"] == [12000, 22000]
    assert eo["benchmark"]["as_of"]
    assert "roughly typical" in summary["methodology_note"].lower()


def test_month_summary_rejects_bad_month(authed):
    client, user_id, headers = authed
    assert client.get("/api/summary/month/2026-7", headers=headers).status_code == 400


# ---------------------------------------------------------------------- tips
def test_tips_generate_and_dismiss_stays_dismissed(authed):
    client, user_id, headers = authed
    account_id = _seed_account(user_id)
    # A quiet small subscription → cancel_candidate tip
    for i, month in enumerate(("2026-03", "2026-04", "2026-05", "2026-06", "2026-07")):
        _seed_txn(account_id, f"app-{i}", amount_minor=-799, local_date=f"{month}-14", counterparty="OldApp", category_key="subscriptions")

    tips = client.get("/api/tips?period=2026-07", headers=headers).json()["tips"]
    cancel = next(t for t in tips if t["rule_key"] == "cancel_candidate")
    assert "!" not in cancel["title"] + cancel["body"]

    client.post(f"/api/tips/{cancel['id']}/dismiss", headers=headers)
    again = client.get("/api/tips?period=2026-07", headers=headers).json()["tips"]
    assert all(t["rule_key"] != "cancel_candidate" for t in again)  # stays dismissed after re-generation


# ------------------------------------------------------------------- recurring
def test_recurring_detection_and_verdict_persists(authed):
    client, user_id, headers = authed
    account_id = _seed_account(user_id)
    # stable £9.99 monthly sub → detected, high confidence
    for i, month in enumerate(("2026-03", "2026-04", "2026-05", "2026-06", "2026-07")):
        _seed_txn(account_id, f"nf-{i}", amount_minor=-999, local_date=f"{month}-14", counterparty="NETFLIX.COM", category_key="subscriptions")
    # Tesco noise → must NOT be detected
    for i, (month, amt) in enumerate((("2026-05", -4212), ("2026-06", -8770), ("2026-07", -2199))):
        _seed_txn(account_id, f"ts-{i}", amount_minor=amt, local_date=f"{month}-03", counterparty="TESCO STORES 3412", category_key="groceries")

    payload = client.get("/api/recurring", headers=headers).json()
    netflix = next(r for r in payload["recurring"] if r["label"] == "NETFLIX.COM")
    assert netflix["cadence"] == "monthly"
    assert netflix["confidence"] >= 0.8
    assert all("TESCO" not in r["label"] for r in payload["recurring"])
    assert payload["totals"]["monthly_committed_minor"] == 999

    # PATCH the verdict → persists, cancelled drops it from committed totals
    client.patch(f"/api/recurring/{netflix['id']}", headers=headers, json={"user_verdict": "cancelled"})
    after = client.get("/api/recurring", headers=headers).json()
    nf_after = next(r for r in after["recurring"] if r["label"] == "NETFLIX.COM")
    assert nf_after["user_verdict"] == "cancelled"
    assert after["totals"]["monthly_committed_minor"] == 0


def test_recurring_patch_rejects_bad_verdict(authed):
    client, user_id, headers = authed
    with SessionLocal() as session:
        row = RecurringPayment(
            user_id=user_id, merchant_key="x", label="X", cadence="monthly", typical_amount_minor=-999,
            first_seen="2026-01-01", last_seen="2026-05-01", occurrences=5, confidence=0.9,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        rid = row.id
    assert client.patch(f"/api/recurring/{rid}", headers=headers, json={"user_verdict": "nope"}).status_code == 400


# ------------------------------------------------------------ one-fetch home
def test_bubbles_aggregate_matches_standalone_endpoints(authed):
    """docs/phases/PHASE-7-dashboard.md item 6 — `GET /api/summary/bubbles`
    returns every bubble's glance payload in one call, and each sub-payload
    is exactly what the matching standalone endpoint returns (shared payload
    functions, so a glance can never disagree with its expanded detail)."""
    client, user_id, headers = authed
    account_id = _seed_account(user_id)
    _seed_txn(account_id, "bub-1", amount_minor=-4212, local_date="2026-07-03", counterparty="TESCO STORES 3412", category_key="groceries")
    client.put(
        "/api/financial-config",
        headers=headers,
        json={"payday_day": 28, "net_monthly_income_minor": 250000, "flat_share_minor": 60000, "buffer_minor": 15000},
    )

    bubbles = client.get("/api/summary/bubbles", headers=headers).json()

    # every §3b roster bubble's data source is present in the one payload
    for key in ("safe_to_spend", "goals", "month_summary", "tips_count", "recurring", "deals", "tax", "sync"):
        assert key in bubbles, f"missing {key}"

    assert bubbles["safe_to_spend"] == client.get("/api/summary/safe-to-spend", headers=headers).json()
    assert bubbles["goals"] == client.get("/api/goals", headers=headers).json()["goals"]
    month = bubbles["month"]
    assert bubbles["month_summary"] == client.get(f"/api/summary/month/{month}", headers=headers).json()
    assert bubbles["tips_count"] == len(client.get(f"/api/tips?period={month}", headers=headers).json()["tips"])
    assert bubbles["recurring"] == client.get("/api/recurring", headers=headers).json()
    assert bubbles["deals"] == client.get("/api/deals", headers=headers).json()
    assert bubbles["sync"] == client.get("/api/sync/status", headers=headers).json()

    # tax glance: §3b row 6 shape — profit fact, honest null estimate with a
    # missing-inputs count (never a guessed figure), unreviewed docs count
    tax = bubbles["tax"]
    year_summary = client.get(f"/api/tax/years/{tax['tax_year']}/summary", headers=headers).json()
    assert tax["profit_minor"] == year_summary["profit_minor"]
    assert tax["estimated_tax_minor"] is None  # Q1/Q5 unanswered — never guesses
    assert tax["missing_inputs_count"] == len(year_summary["missing_inputs"]) > 0
    assert tax["unreviewed_documents"] == 0
