"""app/engines/emergency_fund.py — pure function, docs/PLAN.md §4 S2,
docs/phases/PHASE-9-personal-goals.md §2. No guilt UI (docs/PLAN.md §6 rule
8): every band, including the lowest, must read as calm information.
"""
from __future__ import annotations

from app.engines.emergency_fund import emergency_fund_check


def test_unknown_when_no_essential_spend_history_yet():
    result = emergency_fund_check(500_00, 0, has_active_savings_goal=False)
    assert result == {
        "months_of_cover": None,
        "verdict": "unknown",
        "copy": "Not enough spending history yet to estimate essential monthly costs.",
    }


def test_building_from_scratch_under_one_month():
    result = emergency_fund_check(50_00, 500_00, has_active_savings_goal=False)
    assert result["months_of_cover"] == 0.1
    assert result["verdict"] == "building_from_scratch"
    assert "deliberate trade-off" not in result["copy"]


def test_below_guide_band_one_to_three_months():
    result = emergency_fund_check(1000_00, 500_00, has_active_savings_goal=False)
    assert result["months_of_cover"] == 2.0
    assert result["verdict"] == "below_guide"


def test_exactly_three_months_is_within_range_not_below_guide():
    """docs/phases/PHASE-9 acceptance: "emergency fund at exactly 3.0 months"
    — the phase's own band wording ("1-3mo below guide", "3-6mo within
    range") places the 3.0 boundary in the *higher* band."""
    result = emergency_fund_check(1500_00, 500_00, has_active_savings_goal=False)
    assert result["months_of_cover"] == 3.0
    assert result["verdict"] == "within_range"


def test_exactly_six_months_is_well_covered():
    result = emergency_fund_check(3000_00, 500_00, has_active_savings_goal=False)
    assert result["months_of_cover"] == 6.0
    assert result["verdict"] == "well_covered"


def test_zero_accessible_cash_does_not_crash():
    result = emergency_fund_check(0, 500_00, has_active_savings_goal=True)
    assert result["months_of_cover"] == 0.0
    assert result["verdict"] == "building_from_scratch"


def test_deliberate_trade_off_copy_only_appears_for_low_bands_with_active_goal():
    """docs/phases/PHASE-9 §2's "deliberate copy point": a low reading must
    not read as a failing while a house/rebuild goal is active and behind."""
    low = emergency_fund_check(1000_00, 500_00, has_active_savings_goal=True)
    assert "deliberate trade-off while you're saving toward other goals" in low["copy"]

    well_covered = emergency_fund_check(3000_00, 500_00, has_active_savings_goal=True)
    assert "deliberate trade-off" not in well_covered["copy"]

    low_no_goal = emergency_fund_check(1000_00, 500_00, has_active_savings_goal=False)
    assert "deliberate trade-off" not in low_no_goal["copy"]
