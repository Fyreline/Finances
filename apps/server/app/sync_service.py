"""The Starling sync engine — docs/API.md §1c, docs/DATA_MODEL.md §8.

This is the one module allowed to mix I/O (the Starling client, the DB
session) with orchestration — `engines/` stays pure (docs/ARCHITECTURE.md
§3). Both `routers/sync.py` (the on-demand `POST /api/sync/run` trigger) and
`scripts/sync_providers.py` (the LaunchAgent entrypoint, Phase 8) call
`sync_starling()` directly — neither re-implements the pull/upsert logic.

Idempotency: transactions upsert on `(account_id, provider_uid)`, balance
snapshots on `(account_id, local_date)` — both are real DB unique
constraints (docs/DATA_MODEL.md §2), so a re-run is always safe even if this
module's own bookkeeping had a bug. `new_rows` only counts genuinely new
transaction inserts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .dates import to_local_date
from .engines.categorise import RuleLike, categorise, should_overwrite
from .integrations.starling import NotConfigured, StarlingClient, StarlingUnavailable
from .integrations.trading212 import NotConfigured as T212NotConfigured
from .integrations.trading212 import T212Client, T212Unavailable
from .models import Account, BalanceSnapshot, Category, CategoryRule, SyncRun, Transaction

logger = logging.getLogger(__name__)

_TS_FMT = "%Y-%m-%dT%H:%M:%S.000Z"
_DB_TS_FMT = "%Y-%m-%d %H:%M:%S"


def parse_provider_timestamp(value: str) -> datetime:
    """Starling timestamps are ISO-8601 UTC, e.g.
    `"2026-01-15T10:30:00.000Z"`. `fromisoformat` handles the `Z` suffix
    natively on Python 3.11+, but the explicit replace keeps this robust
    regardless of interpreter version."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_provider_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TS_FMT)


def compute_first_sync_start(account_created_at: str, backfill_floor: str | None) -> datetime:
    """First-ever sync starts at `max(backfill_floor, account_created_at)` —
    whichever is later (docs/API.md §1c): a floor date earlier than the
    account's own existence is pointless, and a floor date later than
    account creation deliberately skips irrelevant pre-floor history."""
    created = parse_provider_timestamp(account_created_at)
    if not backfill_floor:
        return created
    floor = datetime.strptime(backfill_floor, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return max(created, floor)


def compute_pull_start(
    latest_transaction_time: str | None, account_created_at: str, backfill_floor: str | None
) -> datetime:
    """Incremental syncs re-pull the last 7 days (catches late
    settlements/refunds — upsert makes re-fetching free); a first-ever sync
    uses `compute_first_sync_start` (docs/API.md §1c)."""
    if latest_transaction_time:
        return parse_provider_timestamp(latest_transaction_time) - timedelta(days=7)
    return compute_first_sync_start(account_created_at, backfill_floor)


def month_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Chunk `[start, end]` into month-sized windows — docs/API.md §1c
    "in month-sized windows" (keeps any one Starling feed call's response
    small/bounded). Always returns at least one window, even if `start >=
    end` (a same-day incremental sync still needs one call)."""
    if start >= end:
        return [(start, end)]
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        if cursor.month == 12:
            next_boundary = cursor.replace(year=cursor.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_boundary = cursor.replace(month=cursor.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        window_end = min(next_boundary, end)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


@dataclass
class SyncOutcome:
    run: SyncRun
    new_rows: int


def _now_str(dt: datetime) -> str:
    return dt.strftime(_DB_TS_FMT)


async def sync_starling(session: Session, user_id: int, settings: Settings, *, now: datetime | None = None) -> SyncRun:
    """Pull accounts, balances, and the transaction feed from Starling for
    `user_id`, upserting everything idempotently. Degrades to a
    `not_configured` sync_runs row (never raises) when no PAT is set
    (docs/PLAN.md §6 rule 7); degrades to an `error` row (never raises) on
    any Starling/network failure — the caller (router or script) always gets
    a `SyncRun` back, never an exception.
    """
    now = now or datetime.now(timezone.utc)
    started_at = _now_str(now)

    try:
        client = StarlingClient(settings.starling_pat)
    except NotConfigured as exc:
        run = SyncRun(
            provider="starling",
            started_at=started_at,
            finished_at=started_at,
            status="not_configured",
            new_rows=0,
            detail=str(exc),
        )
        session.add(run)
        session.commit()
        return run

    run = SyncRun(provider="starling", started_at=started_at, status="error", new_rows=0)
    session.add(run)
    session.commit()
    session.refresh(run)

    new_rows = 0
    try:
        category_id_by_key = {c.key: c.id for c in session.scalars(select(Category)).all()}
        rules = [
            RuleLike(
                id=r.id,
                priority=r.priority,
                match_field=r.match_field,
                pattern=r.pattern,
                category_id=r.category_id,
                set_is_rental=bool(r.set_is_rental),
                set_exclude=bool(r.set_exclude),
            )
            for r in session.scalars(select(CategoryRule).order_by(CategoryRule.priority)).all()
        ]

        accounts = await client.get_accounts()
        for acc in accounts:
            account_row = session.scalar(
                select(Account).where(Account.provider == "starling", Account.provider_account_uid == acc.account_uid)
            )
            if account_row is None:
                account_row = Account(
                    user_id=user_id,
                    provider="starling",
                    provider_account_uid=acc.account_uid,
                    name=acc.name,
                    kind="current",
                    currency=acc.currency,
                    default_category_uid=acc.default_category_uid,
                )
                session.add(account_row)
                session.commit()
                session.refresh(account_row)
            else:
                account_row.name = acc.name
                account_row.currency = acc.currency
                account_row.default_category_uid = acc.default_category_uid
                session.commit()

            balance = await client.get_balance(acc.account_uid)
            local_date = to_local_date(now)
            snapshot = session.scalar(
                select(BalanceSnapshot).where(
                    BalanceSnapshot.account_id == account_row.id, BalanceSnapshot.local_date == local_date
                )
            )
            if snapshot is None:
                session.add(
                    BalanceSnapshot(
                        account_id=account_row.id,
                        captured_at=started_at,
                        local_date=local_date,
                        balance_minor=balance.cleared_minor,
                        available_minor=balance.effective_minor,
                    )
                )
            else:
                snapshot.captured_at = started_at
                snapshot.balance_minor = balance.cleared_minor
                snapshot.available_minor = balance.effective_minor
            session.commit()

            latest_transaction_time = session.scalar(
                select(Transaction.transaction_time)
                .where(Transaction.account_id == account_row.id)
                .order_by(Transaction.transaction_time.desc())
                .limit(1)
            )
            pull_start = compute_pull_start(latest_transaction_time, acc.created_at, settings.starling_backfill_start or None)
            for window_start, window_end in month_windows(pull_start, now):
                feed_items = await client.get_feed(
                    acc.account_uid,
                    acc.default_category_uid,
                    format_provider_timestamp(window_start),
                    format_provider_timestamp(window_end),
                )
                for item in feed_items:
                    result = categorise(
                        spending_category=item.spending_category,
                        counterparty=item.counter_party_name,
                        reference=item.reference,
                        rules=rules,
                        category_id_by_key=category_id_by_key,
                    )
                    settled = 1 if item.status in ("SETTLED", "ACCOUNT_CHECK") else 0
                    txn_local_date = to_local_date(parse_provider_timestamp(item.transaction_time))

                    existing = session.scalar(
                        select(Transaction).where(
                            Transaction.account_id == account_row.id, Transaction.provider_uid == item.feed_item_uid
                        )
                    )
                    if existing is None:
                        session.add(
                            Transaction(
                                account_id=account_row.id,
                                provider_uid=item.feed_item_uid,
                                amount_minor=item.amount_minor,
                                transaction_time=item.transaction_time,
                                local_date=txn_local_date,
                                settled=settled,
                                counterparty=item.counter_party_name,
                                reference=item.reference,
                                provider_category=item.spending_category,
                                category_id=result.category_id,
                                category_source=result.category_source,
                                is_rental=1 if result.is_rental else 0,
                                exclude_from_spending=1 if result.exclude_from_spending else 0,
                                raw_json=json.dumps(item.raw),
                            )
                        )
                        new_rows += 1
                    else:
                        # Declined/refunded items (and any provider-side edit)
                        # update in place — never a duplicate row
                        # (docs/API.md §1c).
                        existing.amount_minor = item.amount_minor
                        existing.settled = settled
                        existing.counterparty = item.counter_party_name
                        existing.reference = item.reference
                        existing.provider_category = item.spending_category
                        existing.raw_json = json.dumps(item.raw)
                        if should_overwrite(existing.category_source, result.category_source):
                            existing.category_id = result.category_id
                            existing.category_source = result.category_source
                            existing.is_rental = 1 if result.is_rental else 0
                            existing.exclude_from_spending = 1 if result.exclude_from_spending else 0
                session.commit()

        run.status = "ok"
        run.new_rows = new_rows
        run.finished_at = _now_str(datetime.now(timezone.utc))
        session.commit()

        # Recurring detection + tip regeneration run after every successful
        # sync over the freshly-updated feed (docs/phases/PHASE-4-insights.md
        # item 3, docs/API.md §6c). Both are idempotent and preserve the
        # user's verdicts/dismissals; a failure here must never fail the sync,
        # which has already committed its rows.
        try:
            from .dates import now_london
            from .insights_service import rebuild_recurring, rebuild_tips

            rebuild_recurring(session, user_id)
            rebuild_tips(session, user_id, now_london().strftime("%Y-%m"))
        except Exception as exc:  # noqa: BLE001 — insight refresh is best-effort
            logger.warning("post-sync insight refresh failed (sync still ok): %s", exc)

        return run
    except StarlingUnavailable as exc:
        logger.warning("sync_starling: %s", exc)
        run.status = "error"
        run.new_rows = new_rows
        run.detail = str(exc)[:500]
        run.finished_at = _now_str(datetime.now(timezone.utc))
        session.commit()
        return run


async def sync_trading212(session: Session, user_id: int, settings: Settings, *, now: datetime | None = None) -> SyncRun:
    """Pull the T212 account summary and upsert one `balance_snapshots` row
    for the day (docs/API.md §2, docs/phases/PHASE-3-t212-goals.md item 2).
    Same never-raises contract as :func:`sync_starling` — degrades to a
    `not_configured` row when no key/secret is set, an `error` row on any
    T212/network failure, always returns a `SyncRun`.
    """
    now = now or datetime.now(timezone.utc)
    started_at = _now_str(now)

    try:
        client = T212Client(settings.t212_api_key, settings.t212_api_secret, env=settings.t212_env)
    except T212NotConfigured as exc:
        run = SyncRun(
            provider="trading212",
            started_at=started_at,
            finished_at=started_at,
            status="not_configured",
            new_rows=0,
            detail=str(exc),
        )
        session.add(run)
        session.commit()
        return run

    run = SyncRun(provider="trading212", started_at=started_at, status="error", new_rows=0)
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        summary = await client.get_account_summary()

        account_row = session.scalar(
            select(Account).where(Account.provider == "trading212", Account.provider_account_uid == summary.provider_account_id)
        )
        if account_row is None:
            account_row = Account(
                user_id=user_id,
                provider="trading212",
                provider_account_uid=summary.provider_account_id,
                name="Trading 212",
                kind="investment",
                currency=summary.currency,
            )
            session.add(account_row)
            session.commit()
            session.refresh(account_row)
        else:
            account_row.currency = summary.currency
            session.commit()

        detail_json = json.dumps(
            {
                "cash_in_pies_minor": summary.cash_in_pies_minor,
                "cash_reserved_minor": summary.cash_reserved_minor,
                "investments": {
                    "current_value_minor": summary.investments_current_value_minor,
                    "total_cost_minor": summary.investments_total_cost_minor,
                    "realized_pl_minor": summary.investments_realized_pl_minor,
                    "unrealized_pl_minor": summary.investments_unrealized_pl_minor,
                },
            }
        )

        local_date = to_local_date(now)
        new_rows = 0
        snapshot = session.scalar(
            select(BalanceSnapshot).where(
                BalanceSnapshot.account_id == account_row.id, BalanceSnapshot.local_date == local_date
            )
        )
        if snapshot is None:
            session.add(
                BalanceSnapshot(
                    account_id=account_row.id,
                    captured_at=started_at,
                    local_date=local_date,
                    balance_minor=summary.total_value_minor,
                    available_minor=summary.cash_available_minor,
                    detail_json=detail_json,
                )
            )
            new_rows = 1
        else:
            snapshot.captured_at = started_at
            snapshot.balance_minor = summary.total_value_minor
            snapshot.available_minor = summary.cash_available_minor
            snapshot.detail_json = detail_json
        session.commit()

        run.status = "ok"
        run.new_rows = new_rows
        run.finished_at = _now_str(datetime.now(timezone.utc))
        session.commit()
        return run
    except T212Unavailable as exc:
        logger.warning("sync_trading212: %s", exc)
        run.status = "error"
        run.new_rows = 0
        run.detail = str(exc)[:500]
        run.finished_at = _now_str(datetime.now(timezone.utc))
        session.commit()
        return run
