"""routers/deals.py — docs/API.md §5 "Deals", docs/phases/PHASE-6-deals-splits.md
acceptance list. Points DEALS_DIR at a tmp_path per test (monkeypatch) so
nothing here touches the real data/deals/ directory or its seeded fixture.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import app.routers.deals as deals_router
from tests.conftest import auth_headers, make_user

VALID_PAYLOAD = {
    "run_at": "2026-07-13T09:00:00Z",
    "method": "agent_research",
    "sources": [{"url": "https://example.com/rates", "fetched_at": "2026-07-13T09:00:00Z"}],
    "deals": [
        {
            "provider": "Example BS",
            "product": "Easy Access",
            "aer_pct": 4.6,
            "access": "easy",
            "min_deposit_minor": 0,
            "fscs": True,
            "is_isa": False,
            "source_url": "https://example.com/rates",
            "notes": "includes a bonus",
        },
        {
            "provider": "Another BS",
            "product": "Easy Access Plus",
            "aer_pct": 4.8,
            "access": "easy",
            "min_deposit_minor": 100_000,
            "fscs": True,
            "is_isa": False,
            "source_url": "https://example.com/rates-2",
            "notes": None,
        },
    ],
}


def _write_run(tmp_path, filename: str, payload: dict):
    (tmp_path / filename).write_text(json.dumps(payload))


def test_deals_requires_auth(client):
    res = client.get("/api/deals")
    assert res.status_code == 401


def test_deals_empty_before_any_import(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deals_router, "DEALS_DIR", tmp_path)
    user_id = make_user()
    res = client.get("/api/deals", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json() == {"run": None, "deals": [], "stale": False}


def test_import_then_get_returns_the_run_with_both_deals(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deals_router, "DEALS_DIR", tmp_path)
    _write_run(tmp_path, "2026-07-13.json", VALID_PAYLOAD)
    user_id = make_user()
    headers = auth_headers(user_id)

    imp = client.post("/api/deals/import", headers=headers)
    assert imp.status_code == 200
    assert imp.json() == {"imported": 2}

    res = client.get("/api/deals", headers=headers)
    body = res.json()
    assert body["run"]["run_at"] == "2026-07-13T09:00:00Z"
    assert body["run"]["sources"] == VALID_PAYLOAD["sources"]
    assert len(body["deals"]) == 2
    # ordered by aer_pct desc — highest rate first
    assert body["deals"][0]["provider"] == "Another BS"
    assert body["deals"][0]["source_url"] == "https://example.com/rates-2"
    assert body["deals"][1]["provider"] == "Example BS"
    assert body["stale"] is False


def test_import_is_idempotent_per_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deals_router, "DEALS_DIR", tmp_path)
    _write_run(tmp_path, "2026-07-13.json", VALID_PAYLOAD)
    user_id = make_user()
    headers = auth_headers(user_id)

    first = client.post("/api/deals/import", headers=headers)
    assert first.json() == {"imported": 2}
    second = client.post("/api/deals/import", headers=headers)
    assert second.json() == {"imported": 0}  # same file, already imported — no duplicate rows

    res = client.get("/api/deals", headers=headers)
    assert len(res.json()["deals"]) == 2


def test_newest_run_wins_the_display(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deals_router, "DEALS_DIR", tmp_path)
    older = json.loads(json.dumps(VALID_PAYLOAD))
    older["run_at"] = "2026-06-01T09:00:00Z"
    older["deals"] = older["deals"][:1]
    older["deals"][0]["provider"] = "Old Provider"
    _write_run(tmp_path, "2026-06-01.json", older)

    newer = json.loads(json.dumps(VALID_PAYLOAD))
    newer["run_at"] = "2026-07-13T09:00:00Z"
    newer["deals"] = newer["deals"][:1]
    newer["deals"][0]["provider"] = "New Provider"
    _write_run(tmp_path, "2026-07-13.json", newer)

    user_id = make_user()
    headers = auth_headers(user_id)
    client.post("/api/deals/import", headers=headers)  # imports the newer file (lexicographic newest)

    res = client.get("/api/deals", headers=headers)
    assert res.json()["deals"][0]["provider"] == "New Provider"


def test_import_rejects_malformed_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(deals_router, "DEALS_DIR", tmp_path)
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["deals"][0].pop("source_url")
    _write_run(tmp_path, "2026-07-13.json", bad)
    user_id = make_user()
    headers = auth_headers(user_id)

    res = client.post("/api/deals/import", headers=headers)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_deal_run"

    # and nothing was imported — GET still reports no run
    get_res = client.get("/api/deals", headers=headers)
    assert get_res.json()["run"] is None


def test_stale_banner_flag_for_a_run_dated_40_days_back(client, tmp_path, monkeypatch):
    """Clock-forged test (docs/phases/PHASE-6 acceptance) — forges the run's
    own run_at 40 days behind the real now rather than mocking global time."""
    monkeypatch.setattr(deals_router, "DEALS_DIR", tmp_path)
    stale_run_at = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = json.loads(json.dumps(VALID_PAYLOAD))
    payload["run_at"] = stale_run_at
    _write_run(tmp_path, "2026-01-01.json", payload)

    user_id = make_user()
    headers = auth_headers(user_id)
    client.post("/api/deals/import", headers=headers)

    res = client.get("/api/deals", headers=headers)
    assert res.json()["stale"] is True
