"""app/sync_service.py's `sync_trading212()` — respx-stubbed against
tests/fixtures/trading212/ (docs/phases/PHASE-3-t212-goals.md item 2: one
`balance_snapshots` row per account per day, upsert-safe).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import respx
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.integrations.trading212 import LIVE_BASE_URL
from app.models import Account, BalanceSnapshot, SyncRun
from app.sync_service import sync_trading212
from tests.conftest import make_user

FIXTURES = Path(__file__).parent / "fixtures" / "trading212"
BASE = LIVE_BASE_URL
SUMMARY_URL = f"{BASE}/api/v0/equity/account/summary"
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _fixture() -> dict:
    return json.loads((FIXTURES / "account_summary.json").read_text())


def _settings() -> Settings:
    return Settings(t212_api_key="key", t212_api_secret="secret", jwt_secret="test-secret")


def _settings_not_configured() -> Settings:
    return Settings(t212_api_key="", t212_api_secret="", jwt_secret="test-secret")


def test_sync_records_not_configured_run_without_crashing(client):
    user_id = make_user()
    with SessionLocal() as session:
        run = asyncio.run(sync_trading212(session, user_id, _settings_not_configured(), now=NOW))
    assert run.status == "not_configured"
    assert run.new_rows == 0
    assert "KAKEIBO_T212_API_KEY" in (run.detail or "")


@respx.mock
def test_first_sync_creates_account_and_snapshot(client):
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=_fixture()))
    user_id = make_user()
    with SessionLocal() as session:
        run = asyncio.run(sync_trading212(session, user_id, _settings(), now=NOW))

    assert run.status == "ok"
    assert run.new_rows == 1

    with SessionLocal() as session:
        accounts = session.scalars(select(Account).where(Account.provider == "trading212")).all()
        assert len(accounts) == 1
        assert accounts[0].provider_account_uid == "555000111"
        assert accounts[0].kind == "investment"

        snaps = session.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == accounts[0].id)).all()
        assert len(snaps) == 1
        assert snaps[0].balance_minor == 42400
        assert snaps[0].available_minor == 12345
        assert snaps[0].local_date == "2026-06-01"
        detail = json.loads(snaps[0].detail_json)
        assert detail["investments"]["current_value_minor"] == 30055


@respx.mock
def test_rerun_same_day_updates_snapshot_in_place(client):
    """docs/phases/PHASE-3-t212-goals.md acceptance: "T212 fixture sync ->
    snapshot row; second run same day -> updated in place." """
    route = respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=_fixture()))
    user_id = make_user()
    settings = _settings()

    with SessionLocal() as session:
        first = asyncio.run(sync_trading212(session, user_id, settings, now=NOW))
    assert first.new_rows == 1

    updated = _fixture()
    updated["totalValue"] = 500.0
    route.mock(return_value=httpx.Response(200, json=updated))

    with SessionLocal() as session:
        second = asyncio.run(sync_trading212(session, user_id, settings, now=NOW))
    assert second.status == "ok"
    assert second.new_rows == 0, "same local_date -> updates in place, not a new row"

    with SessionLocal() as session:
        snaps = session.scalars(select(BalanceSnapshot)).all()
        assert len(snaps) == 1, "still exactly one snapshot row"
        assert snaps[0].balance_minor == 50000, "the in-place update carries the new value"


@respx.mock
def test_sync_error_recorded_when_t212_unavailable(client):
    respx.get(SUMMARY_URL).mock(side_effect=httpx.ConnectError("refused"))
    user_id = make_user()
    with SessionLocal() as session:
        run = asyncio.run(sync_trading212(session, user_id, _settings(), now=NOW))
    assert run.status == "error"
    assert run.detail
    with SessionLocal() as session:
        rows = session.scalars(select(SyncRun)).all()
        assert len(rows) == 1, "one sync_runs row recorded, app never crashed"
