"""app/engines/affordability.py — the goal-11 affordability mechanic
(docs/PLAN.md §3 row 11, docs/phases/PHASE-9-personal-goals.md §5). Pure
function composed from `engines/goals.GoalProjection`; no I/O.
"""
from __future__ import annotations

from app.engines.affordability import check_affordability
from app.engines.goals import GoalProjection


def _projection(status: str, *, trend=None, catch_up=None) -> GoalProjection:
    return GoalProjection(
        months_remaining=6,
        required_per_month_minor=15_000,
        trend_per_month_minor=trend,
        projected_at_target_minor=1_000_000,
        status=status,
        catch_up_per_month_minor=catch_up,
    )


def test_unknown_when_nothing_is_set_up_yet():
    result = check_affordability(5000, None, None, None)
    assert result["verdict"] == "unknown"


def test_fits_now_when_price_within_headroom():
    result = check_affordability(2000, 5000, None, None)
    assert result["verdict"] == "fits_now"


def test_fits_now_at_exactly_the_headroom_boundary():
    result = check_affordability(5000, 5000, None, None)
    assert result["verdict"] == "fits_now"


def test_not_yet_when_price_exceeds_headroom_and_would_push_goal_from_on_track_to_behind():
    before = _projection("on_track", trend=90_000)
    after = _projection("behind", catch_up=15_000)
    result = check_affordability(500_000, 10_000, before, after)
    assert result["verdict"] == "not_yet"
    assert "week" in result["detail"]


def test_not_yet_weeks_estimate_ceils_never_flatters():
    # £900/month trend, £450 (45000p) price -> exactly half a month -> ~2.17 weeks -> ceils to 3
    before = _projection("on_track", trend=90_000)
    after = _projection("behind", catch_up=1)
    result = check_affordability(45_000, 10_000, before, after)
    assert result["verdict"] == "not_yet"
    assert "roughly 3 weeks" in result["detail"]


def test_not_yet_without_a_trend_gives_no_invented_number():
    """docs/ARCHITECTURE.md §6 — never guesses a figure it can't compute."""
    before = _projection("on_track", trend=None)
    after = _projection("behind", catch_up=15_000)
    result = check_affordability(500_000, 10_000, before, after)
    assert result["verdict"] == "not_yet"
    assert "week" not in result["detail"]


def test_not_yet_when_already_behind_and_catch_up_increases():
    before = _projection("behind", trend=50_000, catch_up=20_000)
    after = _projection("behind", trend=50_000, catch_up=25_000)
    result = check_affordability(300_000, 1_000, before, after)
    assert result["verdict"] == "not_yet"


def test_fits_from_spare_cash_when_goal_stays_on_track():
    before = _projection("on_track", trend=90_000)
    after = _projection("on_track", trend=90_000)
    result = check_affordability(50_000, 10_000, before, after)
    assert result["verdict"] == "fits_from_spare_cash"


def test_fits_from_spare_cash_when_no_goal_to_check_against():
    """Also exercises goal 10's gift-item reuse — no goal projection at all."""
    result = check_affordability(5000, 2000, None, None)
    assert result["verdict"] == "fits_from_spare_cash"


def test_item_costing_more_than_the_entire_goal_target_does_not_crash():
    """docs/phases/PHASE-9 acceptance edge case."""
    before = _projection("on_track", trend=100_000)
    after = _projection("behind", catch_up=999_999)
    result = check_affordability(50_000_000, None, before, after)
    assert result["verdict"] == "not_yet"
    assert isinstance(result["detail"], str)
