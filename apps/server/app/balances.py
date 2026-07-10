"""Shared carry-forward balance aggregation — used by both
`routers/goals.py` (a goal's source-account total + trend series) and
`routers/accounts.py` (`/api/networth`). One account's snapshot on a date
carries forward to every later date until its next snapshot, so summing
across accounts on any date at least one of them reported on never
understates the ones that happened not to sync that exact day
(docs/DATA_MODEL.md §4, §5).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BalanceSnapshot


def carry_forward_series(session: Session, account_ids: list[int]) -> list[tuple[str, dict[int, int]]]:
    """Returns `[(local_date, {account_id: balance_minor, ...}), ...]`
    ascending by date — a date only appears once **every** given account has
    reported at least one snapshot by then, so an early date never
    understates a not-yet-synced account by silently omitting it."""
    if not account_ids:
        return []
    rows = session.scalars(
        select(BalanceSnapshot)
        .where(BalanceSnapshot.account_id.in_(account_ids))
        .order_by(BalanceSnapshot.local_date)
    ).all()

    by_account: dict[int, list[tuple[str, int]]] = {}
    for row in rows:
        by_account.setdefault(row.account_id, []).append((row.local_date, row.balance_minor))
    if not by_account:
        return []

    all_dates = sorted({d for series in by_account.values() for d, _ in series})
    cursors = {account_id: 0 for account_id in by_account}
    last_known: dict[int, int] = {}
    out: list[tuple[str, dict[int, int]]] = []
    for current_date in all_dates:
        for account_id, series in by_account.items():
            while cursors[account_id] < len(series) and series[cursors[account_id]][0] <= current_date:
                last_known[account_id] = series[cursors[account_id]][1]
                cursors[account_id] += 1
        if len(last_known) == len(by_account):
            out.append((current_date, dict(last_known)))
    return out


def sum_series(dated_totals: list[tuple[str, dict[int, int]]]) -> list[tuple[str, int]]:
    return [(d, sum(vals.values())) for d, vals in dated_totals]
