"""routers/sync.py — POST /api/sync/run + GET /api/sync/status
(docs/API.md §5). Runs against the default test env (no
KAKEIBO_STARLING_PAT set, docs/tests/conftest.py), so every run here
exercises the `not_configured` degrade path — the real Starling round-trip
is proven in test_sync_service.py.
"""
from __future__ import annotations

from tests.conftest import auth_headers, make_user


def test_sync_run_requires_auth(client):
    res = client.post("/api/sync/run", json={})
    assert res.status_code == 401


def test_sync_run_defaults_to_starling_and_records_not_configured(client):
    user_id = make_user()
    res = client.post("/api/sync/run", json={}, headers=auth_headers(user_id))
    assert res.status_code == 202
    assert "starling" in res.json()["run_ids"]


def test_sync_run_unimplemented_provider_degrades_gracefully(client):
    user_id = make_user()
    res = client.post("/api/sync/run", json={"providers": ["trading212"]}, headers=auth_headers(user_id))
    assert res.status_code == 202
    assert "trading212" in res.json()["run_ids"]

    status = client.get("/api/sync/status", headers=auth_headers(user_id)).json()
    t212_run = next(r for r in status["runs"] if r["provider"] == "trading212")
    assert t212_run["status"] == "not_configured"


def test_sync_status_empty_before_any_run(client):
    user_id = make_user()
    res = client.get("/api/sync/status", headers=auth_headers(user_id))
    assert res.status_code == 200
    assert res.json() == {"runs": []}


def test_sync_status_returns_latest_run_per_provider(client):
    user_id = make_user()
    client.post("/api/sync/run", json={}, headers=auth_headers(user_id))
    client.post("/api/sync/run", json={}, headers=auth_headers(user_id))

    res = client.get("/api/sync/status", headers=auth_headers(user_id))
    runs = res.json()["runs"]
    starling_runs = [r for r in runs if r["provider"] == "starling"]
    assert len(starling_runs) == 1, "status returns the latest run per provider, not every run"
    assert starling_runs[0]["status"] == "not_configured"
