"""GET /api/goal/service — the static-token sibling read for Sukumo
(routers/service.py, Sukumo's docs/API.md §4).

Auth here is deliberately NOT the per-user JWT flow (app/auth.py) — it's a
single static bearer token (KAKEIBO_SERVICE_TOKEN). Unconfigured paths (no
token, no user yet, no configured house_deposit goal) answer a friendly 503;
a configured token that doesn't match answers 401. Figures throughout are
the generic worked-example placeholders (docs/PRIVATE.md's redaction scheme)
— never the real target/baseline/deadline.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.models import Goal
from tests.conftest import auth_headers, make_user

SERVICE_HEADERS = {"Authorization": "Bearer test-service-token"}


@pytest.fixture
def service_token():
    """Sets KAKEIBO_SERVICE_TOKEN on the live cached Settings object (the
    save/mutate/yield/restore shape Michi's test_service.py established)."""
    settings = get_settings()
    old = settings.service_token
    settings.service_token = "test-service-token"
    yield
    settings.service_token = old


def _seed_goal(user_id: int, **overrides) -> None:
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
        session.add(Goal(**defaults))
        session.commit()


def test_no_token_configured_503s_even_without_auth_header(client):
    res = client.get("/api/goal/service")
    assert res.status_code == 503
    assert res.json()["code"] == "service_not_configured"


def test_token_configured_missing_header_401s(client, service_token):
    res = client.get("/api/goal/service")
    assert res.status_code == 401


def test_token_configured_wrong_token_401s(client, service_token):
    res = client.get("/api/goal/service", headers={"Authorization": "Bearer wrong-token"})
    assert res.status_code == 401


def test_token_ok_but_no_user_yet_503s(client, service_token):
    res = client.get("/api/goal/service", headers=SERVICE_HEADERS)
    assert res.status_code == 503
    assert res.json()["code"] == "service_not_configured"


def test_token_ok_but_no_goal_row_503s(client, service_token):
    make_user()
    res = client.get("/api/goal/service", headers=SERVICE_HEADERS)
    assert res.status_code == 503
    assert res.json()["code"] == "service_not_configured"


def test_token_ok_but_targetless_goal_503s(client, service_token):
    """A house_deposit row without a configured target (seed_goals.py's
    "absent -> not created" can't produce one, but a hand-edited DB could) is
    still the unconfigured state — never report an invented number."""
    user_id = make_user()
    _seed_goal(user_id, target_minor=None, target_date=None)
    res = client.get("/api/goal/service", headers=SERVICE_HEADERS)
    assert res.status_code == 503
    assert res.json()["code"] == "service_not_configured"


def test_configured_goal_no_snapshots_returns_exact_shape_from_baseline(client, service_token):
    """Before any balance snapshots exist the baseline stands in for the
    saved figure (routers/goals.py's fallback), pace is honestly `no_trend`,
    and as_of is the baseline's date."""
    user_id = make_user()
    _seed_goal(user_id)

    res = client.get("/api/goal/service", headers=SERVICE_HEADERS)
    assert res.status_code == 200
    body = res.json()

    assert set(body.keys()) == {"goal_pence", "saved_pence", "pct", "pace_status", "as_of"}
    assert body["goal_pence"] == 1_000_000
    assert body["saved_pence"] == 100_000
    assert body["pct"] == 10.0
    assert body["pace_status"] == "no_trend"
    assert body["as_of"] == "2026-01-01"


def test_configured_goal_with_snapshots_reports_latest_and_floors_pct(client, service_token):
    """With source-account snapshots the saved figure is the summed latest
    balance, as_of is that snapshot's date, the engine's trend verdict comes
    through as pace_status, and pct floors to one decimal place (never
    flatters — docs/ARCHITECTURE.md §6)."""
    user_id = make_user()
    account_id = client.post(
        "/api/accounts/manual",
        json={"name": "Pot", "kind": "savings", "balance_minor": 100_000},
        headers=auth_headers(user_id),
    ).json()["account"]["id"]

    # +90_000/month trend; 333_333/1_000_000 = 33.3333…% -> floors to 33.3.
    for local_date, balance in [("2026-05-31", 153_333), ("2026-06-30", 243_333), ("2026-07-31", 333_333)]:
        client.post(
            f"/api/accounts/{account_id}/balance",
            json={"balance_minor": balance, "local_date": local_date},
            headers=auth_headers(user_id),
        )

    _seed_goal(user_id, source_account_ids=f"[{account_id}]")

    res = client.get("/api/goal/service", headers=SERVICE_HEADERS)
    assert res.status_code == 200
    body = res.json()

    assert body["goal_pence"] == 1_000_000
    assert body["saved_pence"] == 333_333
    assert body["pct"] == 33.3
    assert body["pace_status"] in {"on_track", "behind"}
    assert body["as_of"] == "2026-07-31"


def test_service_response_carries_no_extra_fields_or_series(client, service_token):
    """The snapshot contract (Sukumo docs/DATA_MODEL.md §6): exactly the five
    agreed fields — in particular no series, no required_per_month, none of
    the richer authed-goal payload."""
    user_id = make_user()
    _seed_goal(user_id)

    body = client.get("/api/goal/service", headers=SERVICE_HEADERS).json()
    assert set(body.keys()) == {"goal_pence", "saved_pence", "pct", "pace_status", "as_of"}
