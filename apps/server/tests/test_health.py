"""routers/health.py — status + cached identity reachability probe + the
all-not_configured integrations flags (docs/AUTH.md §3, docs/SECRETS.md)."""
from __future__ import annotations

import httpx
import respx

MISHKA_BASE = "http://127.0.0.1:8000"


@respx.mock
def test_health_reachable(client):
    respx.get(f"{MISHKA_BASE}/api/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["identity"] == "reachable"
    assert body["integrations"] == {
        "starling": "not_configured",
        "trading212": "not_configured",
        "gmail": "not_configured",
    }


@respx.mock
def test_health_unreachable_when_mishka_down(client):
    route = respx.get(f"{MISHKA_BASE}/api/health").mock(side_effect=httpx.ConnectError("refused"))
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["identity"] == "unreachable"
    assert route.called


@respx.mock
def test_health_reachability_is_cached(client):
    route = respx.get(f"{MISHKA_BASE}/api/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    client.get("/api/health")
    client.get("/api/health")
    client.get("/api/health")
    assert route.call_count == 1, "the 60s cache should short-circuit repeat probes"


def test_health_does_not_require_auth(client):
    res = client.get("/api/health")
    assert res.status_code == 200


def test_health_never_leaks_balances_or_counts(client):
    """docs/AUTH.md §3: health returns liveness + integration flags (and the
    docs/API.md §5 last-sync timestamps) only — no balances, no counts."""
    res = client.get("/api/health")
    body = res.json()
    assert set(body.keys()) == {"status", "identity", "integrations", "last_sync"}
    assert body["last_sync"] == {"starling": None, "trading212": None, "gmail": None}


def test_health_reports_error_and_stale_and_last_sync(client, monkeypatch):
    """docs/API.md §5: integration values are ok|not_configured|error|stale,
    with last_sync = the latest successful run's timestamp (Phase 8 fix —
    the router previously returned an off-contract "configured" and omitted
    last_sync entirely)."""
    from datetime import datetime, timedelta, timezone

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import SyncRun

    settings = get_settings()
    monkeypatch.setattr(settings, "starling_pat", "fake-pat-for-status-shape-test")
    monkeypatch.setattr(settings, "t212_api_key", "fake-key")
    monkeypatch.setattr(settings, "t212_api_secret", "fake-secret")

    fmt = "%Y-%m-%d %H:%M:%S"
    fresh = datetime.now(timezone.utc).strftime(fmt)
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).strftime(fmt)
    with SessionLocal() as session:
        # starling: an old ok run then a newer error run -> "error"
        session.add(SyncRun(provider="starling", started_at=old, finished_at=old, status="ok", new_rows=1))
        session.add(SyncRun(provider="starling", started_at=fresh, finished_at=fresh, status="error", new_rows=0, detail="boom"))
        # trading212: last ok run 72h ago -> "stale", last_sync carries it
        session.add(SyncRun(provider="trading212", started_at=old, finished_at=old, status="ok", new_rows=1))
        session.commit()

    body = client.get("/api/health").json()
    assert body["integrations"]["starling"] == "error"
    assert body["integrations"]["trading212"] == "stale"
    assert body["integrations"]["gmail"] == "not_configured"
    assert body["last_sync"]["trading212"] == old
    assert body["last_sync"]["gmail"] is None
