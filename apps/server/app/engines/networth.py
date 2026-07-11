"""Net worth aggregation — docs/PLAN.md §4 S1, docs/phases/PHASE-9-personal-goals.md
§1. Pure functions over the carry-forward balance series `app/balances.py`
already computes for goals (docs/ARCHITECTURE.md §3 "engines are pure
functions over rows + config") — no I/O, no new money model.
"""
from __future__ import annotations

from datetime import datetime, timedelta

_DATE_FMT = "%Y-%m-%d"


def net_worth_series(
    dated_totals: list[tuple[str, dict[int, int]]], *, window_days: int | None = None
) -> list[dict]:
    """`dated_totals`: ascending `(local_date, {account_id: balance_minor})`
    pairs from `balances.carry_forward_series`. Returns `[{date,
    total_minor}]` ascending. `window_days`, if given, keeps only points
    within that many days of the series' own latest date (docs/phases/
    PHASE-9 §1 "one 90-day sparkline") — zero accounts/snapshots yields `[]`,
    never a crash."""
    series = [{"date": d, "total_minor": sum(by_account.values())} for d, by_account in dated_totals]
    if window_days is None or not series:
        return series
    last_date = datetime.strptime(series[-1]["date"], _DATE_FMT).date()
    cutoff = last_date - timedelta(days=window_days)
    return [p for p in series if datetime.strptime(p["date"], _DATE_FMT).date() > cutoff]


def net_worth_now(accounts: list[dict], dated_totals: list[tuple[str, dict[int, int]]]) -> dict:
    """`accounts`: `[{id, name}]` for every `include_in_networth` account
    (the router loads these; this stays pure over plain dicts, matching the
    rest of `engines/`). Returns `{total_minor, by_account: [{account_id,
    name, balance_minor}]}` as of the latest date in `dated_totals` —
    `{total_minor: 0, by_account: []}` with zero accounts or zero snapshots
    yet, the fresh-setup-state acceptance case (docs/phases/PHASE-9
    "acceptance": "net worth with zero accounts")."""
    if not dated_totals:
        return {"total_minor": 0, "by_account": []}
    _, latest = dated_totals[-1]
    name_by_id = {a["id"]: a["name"] for a in accounts}
    by_account = [
        {"account_id": account_id, "name": name_by_id.get(account_id, "Account"), "balance_minor": balance}
        for account_id, balance in latest.items()
    ]
    return {"total_minor": sum(latest.values()), "by_account": by_account}
