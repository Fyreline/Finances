"""routers/auth.py — login (proxy verify)/refresh/rotate/reuse-tripwire/
settings, with the identity call stubbed via respx (docs/AUTH.md,
docs/phases/PHASE-1-scaffold.md).
"""
from __future__ import annotations

import httpx
import respx

MISHKA_BASE = "http://127.0.0.1:8000"


def _mock_mishka_login_success(email="mack@example.com", display_name="Mack", mishka_id=1):
    respx.post(f"{MISHKA_BASE}/api/auth/login").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "throwaway",
                "refresh_token": "throwaway-refresh",
                "expires_in": 900,
                "user": {"id": mishka_id, "email": email, "display_name": display_name},
            },
        )
    )
    respx.post(f"{MISHKA_BASE}/api/auth/logout").mock(return_value=httpx.Response(200, json={"logged_out": True}))


@respx.mock
def test_login_success_issues_tokens_and_upserts_user(client):
    _mock_mishka_login_success()
    res = client.post("/api/auth/login", json={"email": "Mack@Example.com", "password": "hunter2"})
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["email"] == "mack@example.com"
    assert body["user"]["display_name"] == "Mack"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 15 * 60


@respx.mock
def test_login_display_name_refreshes_on_second_login(client):
    _mock_mishka_login_success(display_name="Mack")
    client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})

    _mock_mishka_login_success(display_name="Mack Renamed")
    res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    assert res.json()["user"]["display_name"] == "Mack Renamed"


@respx.mock
def test_login_wrong_password_returns_401(client):
    respx.post(f"{MISHKA_BASE}/api/auth/login").mock(
        return_value=httpx.Response(401, json={"detail": "no", "code": "invalid_credentials"})
    )
    res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "wrong"})
    assert res.status_code == 401
    assert res.json()["code"] == "invalid_credentials"


@respx.mock
def test_login_mishka_down_returns_503(client):
    respx.post(f"{MISHKA_BASE}/api/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    assert res.status_code == 503
    assert res.json()["code"] == "identity_unavailable"


@respx.mock
def test_login_mishka_rate_limited_returns_429(client):
    respx.post(f"{MISHKA_BASE}/api/auth/login").mock(return_value=httpx.Response(429, json={"detail": "slow down"}))
    res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    assert res.status_code == 429
    assert res.json()["code"] == "rate_limited"


@respx.mock
def test_repeated_failed_logins_trip_kakeibos_own_rate_limit(client):
    respx.post(f"{MISHKA_BASE}/api/auth/login").mock(
        return_value=httpx.Response(401, json={"detail": "no", "code": "invalid_credentials"})
    )
    for _ in range(5):
        res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "wrong"})
        assert res.status_code == 401
    # 6th attempt in the window: Kakeibo's own limiter trips before even calling Mishka.
    res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "wrong"})
    assert res.status_code == 429
    assert res.json()["code"] == "rate_limited"


@respx.mock
def test_refresh_rotates_token(client):
    _mock_mishka_login_success()
    login_res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    old_refresh = login_res.json()["refresh_token"]

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert refresh_res.status_code == 200
    new_refresh = refresh_res.json()["refresh_token"]
    assert new_refresh != old_refresh

    # The old (now-rotated-away) token is spent.
    reuse_res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse_res.status_code == 401
    assert reuse_res.json()["code"] == "refresh_reuse_detected"


@respx.mock
def test_refresh_reuse_revokes_all_sessions(client):
    _mock_mishka_login_success()
    login_res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    old_refresh = login_res.json()["refresh_token"]

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    new_refresh = refresh_res.json()["refresh_token"]

    reuse_res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse_res.status_code == 401
    assert reuse_res.json()["code"] == "refresh_reuse_detected"

    # The tripwire revoked EVERY session, including the one just rotated to.
    followup = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
    assert followup.status_code == 401
    assert followup.json()["code"] == "refresh_reuse_detected"


@respx.mock
def test_refresh_unknown_token_rejected(client):
    res = client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert res.status_code == 401
    assert res.json()["code"] == "invalid_refresh_token"


@respx.mock
def test_logout_revokes_token(client):
    _mock_mishka_login_success()
    login_res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    refresh_token = login_res.json()["refresh_token"]

    logout_res = client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    assert logout_res.status_code == 200
    assert logout_res.json()["logged_out"] is True

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_res.status_code == 401


@respx.mock
def test_logout_unknown_token_is_still_200(client):
    res = client.post("/api/auth/logout", json={"refresh_token": "never-issued"})
    assert res.status_code == 200
    assert res.json()["logged_out"] is True


def test_me_requires_auth(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_settings_requires_auth(client):
    res = client.put("/api/auth/settings", json={"hidden_suggestions": ["S4"]})
    assert res.status_code == 401


@respx.mock
def test_me_and_settings_merge_patch(client):
    _mock_mishka_login_success()
    login_res = client.post("/api/auth/login", json={"email": "mack@example.com", "password": "hunter2"})
    access_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["settings"] == {}
    assert me_res.json()["email"] == "mack@example.com"

    patch_res = client.put(
        "/api/auth/settings",
        json={"hidden_suggestions": ["S4"], "dashboard_tiles_order": ["safe_to_spend"]},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["settings"] == {
        "hidden_suggestions": ["S4"],
        "dashboard_tiles_order": ["safe_to_spend"],
    }

    # A second, partial patch merges rather than clobbers.
    patch_res_2 = client.put("/api/auth/settings", json={"hidden_suggestions": []}, headers=headers)
    assert patch_res_2.json()["settings"] == {
        "hidden_suggestions": [],
        "dashboard_tiles_order": ["safe_to_spend"],
    }

    me_res2 = client.get("/api/auth/me", headers=headers)
    assert me_res2.json()["settings"] == {
        "hidden_suggestions": [],
        "dashboard_tiles_order": ["safe_to_spend"],
    }


def test_invalid_bearer_token_rejected(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_no_argon2_anywhere():
    """docs/AUTH.md §4: grep -ri argon2 apps/server must return nothing."""
    import subprocess
    from pathlib import Path

    server_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["grep", "-ril", "argon2", str(server_dir / "app")],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", f"argon2 reference found: {result.stdout}"


def test_no_password_hash_anywhere():
    """docs/AUTH.md §4: grep -ri password_hash apps/server must return nothing."""
    import subprocess
    from pathlib import Path

    server_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["grep", "-ril", "password_hash", str(server_dir / "app")],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", f"password_hash reference found: {result.stdout}"


def test_401_sweep_over_every_openapi_route(client):
    """docs/AUTH.md §4 / PHASE-8 §1: every non-auth endpoint returns 401
    without a token — a scripted sweep over the real OpenAPI route list, not
    a spot check. Exemptions are exactly the documented anonymous surface:
    login, refresh, logout (it authenticates via the refresh token in its own
    body) and health (liveness flags only, never balances)."""
    exempt = {"/api/auth/login", "/api/auth/refresh", "/api/auth/logout", "/api/health"}
    dummies = {
        "tax_year": "2026-27",
        "yyyy_mm": "2026-07",
        "month": "2026-07",
        "key": "house_deposit",
    }
    schema = client.app.openapi()
    swept = 0
    failures = []
    for path, methods in schema["paths"].items():
        if path in exempt:
            continue
        concrete = path
        for name, value in dummies.items():
            concrete = concrete.replace("{" + name + "}", value)
        # Any remaining {param} is an integer id.
        import re

        concrete = re.sub(r"\{[^}]+\}", "1", concrete)
        for method in methods:
            res = client.request(method.upper(), concrete)  # no Authorization header
            swept += 1
            if res.status_code != 401:
                failures.append(f"{method.upper()} {concrete} -> {res.status_code}")
    assert swept > 0
    assert failures == [], f"unauthenticated access not rejected: {failures}"
