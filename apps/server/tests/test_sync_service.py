"""app/sync_service.py — pure window-math tests plus a full sync exercised
against the fixtures in tests/fixtures/starling/ via respx (no live calls,
docs/phases/PHASE-2-starling.md). Proves the phase's two hard acceptance
items: idempotent re-run (zero new rows second time) and a manual
recategorisation surviving a re-sync.
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
from app.models import Account, BalanceSnapshot, SyncRun, Transaction
from app.sync_service import compute_first_sync_start, compute_pull_start, month_windows, sync_starling
from tests.conftest import make_user

FIXTURES = Path(__file__).parent / "fixtures" / "starling"
BASE = "https://api.starlingbank.com"
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_starling_routes(feed_fixture: str = "feed.json") -> respx.Route:
    """Registers all three Starling routes the sync engine calls; returns the
    feed route so a test can later call `.mock(...)` again on the *same*
    Route object to change its response for a subsequent sync call (respx
    matches routes in registration order, so re-registering a fresh route
    for the same URL would silently never be reached — mutating the
    existing Route is the supported way to change behaviour mid-test)."""
    respx.get(f"{BASE}/api/v2/accounts").mock(return_value=httpx.Response(200, json=_fixture("accounts.json")))
    respx.get(f"{BASE}/api/v2/accounts/acc-0001-primary/balance").mock(
        return_value=httpx.Response(200, json=_fixture("balance.json"))
    )
    return respx.get(
        f"{BASE}/api/v2/feed/account/acc-0001-primary/category/cat-0001-default/transactions-between"
    ).mock(return_value=httpx.Response(200, json=_fixture(feed_fixture)))


def _settings() -> Settings:
    return Settings(starling_pat="fake-pat", jwt_secret="test-secret")


def _settings_not_configured() -> Settings:
    return Settings(starling_pat="", jwt_secret="test-secret")


# --------------------------------------------------------------- pure window
def test_compute_first_sync_start_uses_account_creation_when_no_floor():
    started = compute_first_sync_start("2026-05-01T09:00:00.000Z", None)
    assert started == datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


def test_compute_first_sync_start_floor_wins_when_later_than_creation():
    started = compute_first_sync_start("2020-01-01T00:00:00.000Z", "2024-03-01")
    assert started == datetime(2024, 3, 1, tzinfo=timezone.utc), "floor is later than account creation, so it wins"


def test_compute_first_sync_start_creation_wins_when_later_than_floor():
    started = compute_first_sync_start("2026-05-01T09:00:00.000Z", "2020-01-01")
    assert started == datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc), "account creation is later, so it wins"


def test_compute_pull_start_incremental_uses_seven_day_overlap():
    started = compute_pull_start("2026-05-20T09:00:00.000Z", "2026-01-01T00:00:00.000Z", None)
    assert started == datetime(2026, 5, 13, 9, 0, 0, tzinfo=timezone.utc)


def test_compute_pull_start_first_sync_ignores_overlap():
    started = compute_pull_start(None, "2026-05-01T09:00:00.000Z", None)
    assert started == datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


def test_month_windows_chunks_by_calendar_month():
    start = datetime(2026, 5, 15, tzinfo=timezone.utc)
    end = datetime(2026, 7, 10, tzinfo=timezone.utc)
    windows = month_windows(start, end)
    assert windows == [
        (datetime(2026, 5, 15, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc)),
        (datetime(2026, 6, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, tzinfo=timezone.utc)),
        (datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 10, tzinfo=timezone.utc)),
    ]


def test_month_windows_same_day_returns_one_window():
    start = end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert month_windows(start, end) == [(start, end)]


def test_month_windows_year_boundary():
    start = datetime(2025, 12, 20, tzinfo=timezone.utc)
    end = datetime(2026, 1, 15, tzinfo=timezone.utc)
    windows = month_windows(start, end)
    assert windows == [
        (datetime(2025, 12, 20, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc)),
    ]


# ------------------------------------------------------------------- sync
def test_sync_records_not_configured_run_without_crashing(client):
    user_id = make_user()
    with SessionLocal() as session:
        run = asyncio.run(sync_starling(session, user_id, _settings_not_configured(), now=NOW))
    assert run.status == "not_configured"
    assert run.new_rows == 0
    assert "KAKEIBO_STARLING_PAT" in (run.detail or "")


@respx.mock
def test_first_sync_creates_account_transactions_and_snapshot(client):
    _mock_starling_routes()
    user_id = make_user()
    with SessionLocal() as session:
        run = asyncio.run(sync_starling(session, user_id, _settings(), now=NOW))

    assert run.status == "ok"
    assert run.new_rows == 5, "the fixture feed has 5 synthetic items"

    with SessionLocal() as session:
        accounts = session.scalars(select(Account)).all()
        assert len(accounts) == 1
        assert accounts[0].provider_account_uid == "acc-0001-primary"
        assert accounts[0].default_category_uid == "cat-0001-default"

        txns = session.scalars(select(Transaction)).all()
        assert len(txns) == 5

        grocery = next(t for t in txns if t.provider_uid == "feed-0001")
        assert grocery.amount_minor == -4599
        assert grocery.category_source == "provider"

        snaps = session.scalars(select(BalanceSnapshot)).all()
        assert len(snaps) == 1
        assert snaps[0].balance_minor == 123456
        assert snaps[0].available_minor == 120000


@respx.mock
def test_rerun_is_idempotent_zero_new_rows(client):
    """Phase 2's headline acceptance item: a re-run must never duplicate a
    row (docs/DATA_MODEL.md §8, docs/phases/PHASE-2-starling.md)."""
    _mock_starling_routes()
    user_id = make_user()
    settings = _settings()

    with SessionLocal() as session:
        first = asyncio.run(sync_starling(session, user_id, settings, now=NOW))
    assert first.new_rows == 5

    with SessionLocal() as session:
        second = asyncio.run(sync_starling(session, user_id, settings, now=NOW))
    assert second.status == "ok"
    assert second.new_rows == 0, "re-running against the same fixtures must create zero new rows"

    with SessionLocal() as session:
        txns = session.scalars(select(Transaction)).all()
        assert len(txns) == 5, "still exactly 5 rows, none duplicated"

        snaps = session.scalars(select(BalanceSnapshot)).all()
        assert len(snaps) == 1, "same local_date -> the snapshot updates in place, not a second row"


@respx.mock
def test_manual_categorisation_survives_a_resync(client):
    _mock_starling_routes()
    user_id = make_user()
    settings = _settings()

    with SessionLocal() as session:
        asyncio.run(sync_starling(session, user_id, settings, now=NOW))

    with SessionLocal() as session:
        txn = session.scalar(select(Transaction).where(Transaction.provider_uid == "feed-0001"))
        txn.category_id = None
        txn.category_source = "manual"
        txn.is_rental = 1
        session.commit()

    with SessionLocal() as session:
        run = asyncio.run(sync_starling(session, user_id, settings, now=NOW))
    assert run.status == "ok"
    assert run.new_rows == 0

    with SessionLocal() as session:
        txn = session.scalar(select(Transaction).where(Transaction.provider_uid == "feed-0001"))
        assert txn.category_source == "manual", "a re-sync must never demote a manual categorisation"
        assert txn.is_rental == 1, "the manual is_rental flag must survive too"


@respx.mock
def test_declined_or_amount_change_updates_in_place_not_duplicated(client):
    """docs/API.md §1c: 'Declined/refunded items update in place, never
    duplicate.' Simulated here as a second sync where the fixture feed
    reports a different status/amount for the same feedItemUid."""
    feed_route = _mock_starling_routes()
    user_id = make_user()
    settings = _settings()

    with SessionLocal() as session:
        asyncio.run(sync_starling(session, user_id, settings, now=NOW))

    updated_feed = _fixture("feed.json")
    updated_feed["feedItems"][3]["status"] = "DECLINED"  # feed-0004 was PENDING
    feed_route.mock(return_value=httpx.Response(200, json=updated_feed))

    with SessionLocal() as session:
        run = asyncio.run(sync_starling(session, user_id, settings, now=NOW))
    assert run.new_rows == 0

    with SessionLocal() as session:
        txns = session.scalars(select(Transaction).where(Transaction.provider_uid == "feed-0004")).all()
        assert len(txns) == 1, "status change must update in place, never duplicate"
        assert txns[0].settled == 0


@respx.mock
def test_sync_error_recorded_when_starling_unavailable(client):
    respx.get(f"{BASE}/api/v2/accounts").mock(side_effect=httpx.ConnectError("refused"))
    user_id = make_user()
    with SessionLocal() as session:
        run = asyncio.run(sync_starling(session, user_id, _settings(), now=NOW))
    assert run.status == "error"
    assert run.detail
    with SessionLocal() as session:
        rows = session.scalars(select(SyncRun)).all()
        assert len(rows) == 1, "one sync_runs row recorded, app never crashed"
