"""app/engines/networth.py — pure functions, docs/phases/PHASE-9-personal-goals.md §1."""
from __future__ import annotations

from app.engines.networth import net_worth_now, net_worth_series


def test_net_worth_series_empty_with_no_snapshots():
    assert net_worth_series([]) == []


def test_net_worth_series_sums_by_date():
    dated = [
        ("2026-07-01", {1: 1000, 2: 2000}),
        ("2026-07-02", {1: 1500, 2: 2500}),
    ]
    assert net_worth_series(dated) == [
        {"date": "2026-07-01", "total_minor": 3000},
        {"date": "2026-07-02", "total_minor": 4000},
    ]


def test_net_worth_series_windows_to_recent_days():
    dated = [
        ("2026-01-01", {1: 100}),
        ("2026-06-01", {1: 200}),
        ("2026-07-01", {1: 300}),
    ]
    windowed = net_worth_series(dated, window_days=90)
    assert [p["date"] for p in windowed] == ["2026-06-01", "2026-07-01"]


def test_net_worth_now_zero_with_no_accounts():
    """docs/phases/PHASE-9 acceptance: "net worth with zero accounts"."""
    assert net_worth_now([], []) == {"total_minor": 0, "by_account": []}


def test_net_worth_now_uses_latest_date_with_account_names():
    accounts = [{"id": 1, "name": "Starling current"}, {"id": 2, "name": "Cash ISA elsewhere"}]
    dated = [
        ("2026-07-01", {1: 1000, 2: 2000}),
        ("2026-07-02", {1: 1500, 2: 2500}),
    ]
    result = net_worth_now(accounts, dated)
    assert result["total_minor"] == 4000
    by_name = {row["name"]: row["balance_minor"] for row in result["by_account"]}
    assert by_name == {"Starling current": 1500, "Cash ISA elsewhere": 2500}


def test_net_worth_now_falls_back_to_generic_name_for_unknown_account():
    dated = [("2026-07-01", {99: 500})]
    result = net_worth_now([], dated)
    assert result["by_account"] == [{"account_id": 99, "name": "Account", "balance_minor": 500}]
