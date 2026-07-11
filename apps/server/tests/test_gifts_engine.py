"""app/engines/gifts.py — pure function, docs/PLAN.md §3 row 10,
docs/phases/PHASE-9-personal-goals.md §4.
"""
from __future__ import annotations

from app.engines.gifts import occasion_summary


def test_occasion_with_zero_items_and_no_limit():
    """docs/phases/PHASE-9 acceptance: "gift occasion with zero items". No
    limit is ever invented (docs/PRIVATE.md)."""
    result = occasion_summary(None, [])
    assert result == {"spent_minor": 0, "limit_minor": None, "remaining_minor": None, "verdict": "no_limit_set"}


def test_occasion_with_zero_items_and_a_limit_is_under_limit():
    result = occasion_summary(10_000, [])
    assert result == {"spent_minor": 0, "limit_minor": 10_000, "remaining_minor": 10_000, "verdict": "under_limit"}


def test_occasion_under_limit():
    result = occasion_summary(10_000, [3_000, 2_000])
    assert result == {"spent_minor": 5_000, "limit_minor": 10_000, "remaining_minor": 5_000, "verdict": "under_limit"}


def test_occasion_over_limit_is_calm_information_not_a_crash():
    result = occasion_summary(10_000, [7_000, 5_000])
    assert result == {"spent_minor": 12_000, "limit_minor": 10_000, "remaining_minor": -2_000, "verdict": "over_limit"}


def test_occasion_exactly_at_limit_is_under_limit():
    result = occasion_summary(10_000, [10_000])
    assert result["verdict"] == "under_limit"
    assert result["remaining_minor"] == 0
