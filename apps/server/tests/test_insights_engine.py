"""app/engines/insights.py — safe-to-spend (§6a), month summary (§6b), tips
(§6c). Pure maths; all figures synthetic placeholders (docs/PRIVATE.md).
"""
from __future__ import annotations

from datetime import date

from app.engines.insights import (
    CategoryMonthInput,
    CommittedInput,
    DetectedIncome,
    FinancialConfigLike,
    GoalSetAsideInput,
    months_to_next_31_jan,
    month_summary,
    payday_period,
    payday_period_from_detected,
    safe_to_spend,
    tip_cancel_candidates,
    tip_category_trending_up,
    tip_discretionary_variance,
    tip_emergency_fund_low,
    tip_price_rises,
    tip_sa_registration_deadline,
    tip_tax_setaside_gap,
)


# ===================================================================== §6a
def test_payday_period_mid_period():
    start, end = payday_period("2026-07-15", 28)
    assert start.isoformat() == "2026-06-28"
    assert end.isoformat() == "2026-07-27"


def test_payday_period_on_payday_is_period_start():
    start, end = payday_period("2026-07-28", 28)
    assert start.isoformat() == "2026-07-28"
    assert end.isoformat() == "2026-08-27"


def test_payday_period_clamps_31st_in_february():
    start, end = payday_period("2026-02-15", 31)
    assert start.isoformat() == "2026-01-31"
    assert end.isoformat() == "2026-02-27"  # day before 28 Feb (clamped payday)


def test_months_to_next_31_jan():
    assert months_to_next_31_jan("2026-07-15") == 6
    assert months_to_next_31_jan("2027-01-15") == 1  # never zero
    assert months_to_next_31_jan("2027-02-01") == 11


# --------------------------------------- §6a Phase 11: detected payday period
# Actual last-Friday-of-the-month dates through 2026 (Jan 30 … Jul 31): the
# calendar-day gaps between them are 28/28/28/35/28/35 — clustered but not a
# fixed day-of-month, exactly the pattern payday_day (a literal 1–31) can't
# represent. Median gap 28 → a monthly-ish period, no weekday rule needed.
_LAST_FRIDAY_GAPS = [28, 28, 28, 35, 28, 35]


def test_payday_period_from_detected_current_period():
    start, end = payday_period_from_detected(date(2026, 7, 31), _LAST_FRIDAY_GAPS, date(2026, 8, 5))
    assert start.isoformat() == "2026-07-31"  # period starts at the last real salary
    assert end.isoformat() == "2026-08-27"  # + median gap (28) - 1 day


def test_payday_period_from_detected_rolls_forward_when_next_salary_not_synced_yet():
    """A real, expected case: the app is opened a little into the next period
    before the next salary transaction has synced — roll the window forward by
    the median gap rather than reporting a stale, already-ended period."""
    start, end = payday_period_from_detected(date(2026, 7, 31), _LAST_FRIDAY_GAPS, date(2026, 9, 10))
    assert start.isoformat() == "2026-08-28"
    assert end.isoformat() == "2026-09-24"


def test_payday_period_from_detected_degenerate_gaps_never_zero_length():
    start, end = payday_period_from_detected(date(2026, 7, 31), [0, 0], date(2026, 7, 31))
    assert start == date(2026, 7, 31)
    assert end == date(2026, 7, 31)  # a single day, never an inverted window


def _detected(**kw) -> DetectedIncome:
    base = dict(
        net_income_minor=210_000,
        last_seen=date(2026, 7, 31),
        gaps_days=list(_LAST_FRIDAY_GAPS),
        cadence="monthly",
        occurrences=7,
        confidence=0.9,
        label="ACME PAYROLL",
    )
    base.update(kw)
    return DetectedIncome(**base)


def test_safe_to_spend_uses_detected_income_and_marks_it_detected():
    """docs/phases/PHASE-11 acceptance: with no manual payday/income but a
    confident salary anchor, the period + net income come from history and are
    VISIBLY marked detected (never presented as if typed in)."""
    result = safe_to_spend(
        config=_config(payday_day=None, net_monthly_income_minor=None, flat_share_minor=0),
        today="2026-08-05",
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
        detected_income=_detected(),
    )
    assert result.setup_missing == []
    assert result.safe_to_spend_minor == 210_000 - 15_000  # income - buffer
    assert result.net_income_minor == 210_000
    assert result.payday_source == "detected"
    assert result.net_income_source == "detected"
    assert result.period_start == "2026-07-31" and result.period_end == "2026-08-27"
    # human-auditable detail, not a raw opaque number
    assert result.detected_income["label"] == "ACME PAYROLL"
    assert result.detected_income["median_gap_days"] == 28
    assert result.detected_income["typical_amount_minor"] == 210_000
    assert result.detected_income["confidence"] == 0.9


def test_manual_config_always_wins_over_detection():
    """docs/phases/PHASE-11 §2: an explicitly set payday/income is used exactly
    as before and reported 'manual' — a detection never overrides it."""
    result = safe_to_spend(
        config=_config(payday_day=28, net_monthly_income_minor=250_000, flat_share_minor=0),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
        detected_income=_detected(net_income_minor=999_999, last_seen=date(2026, 7, 31)),
    )
    assert result.payday_source == "manual"
    assert result.net_income_source == "manual"
    assert result.net_income_minor == 250_000  # NOT the detected 999,999
    assert result.period_start == "2026-06-28"  # manual payday_day=28, not detected 31
    assert result.detected_income is None  # nothing detected was used


def test_manual_payday_but_detected_income_is_per_field():
    """Manual and detected can coexist per-field: a manually set payday with an
    unset income still borrows the detected income (and says so)."""
    result = safe_to_spend(
        config=_config(payday_day=28, net_monthly_income_minor=None, flat_share_minor=0),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
        detected_income=_detected(net_income_minor=210_000),
    )
    assert result.payday_source == "manual"
    assert result.net_income_source == "detected"
    assert result.net_income_minor == 210_000
    assert result.period_start == "2026-06-28"  # manual payday still wins for the period


def test_safe_to_spend_setup_missing_when_neither_manual_nor_detected():
    """A brand-new account: no manual config, no detectable salary yet → the
    setup_missing fallback must not regress, and both sources are null."""
    result = safe_to_spend(
        config=_config(payday_day=None, net_monthly_income_minor=None),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
        detected_income=None,
    )
    assert result.safe_to_spend_minor is None
    assert result.setup_missing == ["payday_day", "net_monthly_income"]
    assert result.payday_source is None
    assert result.net_income_source is None
    assert result.detected_income is None


def _config(**kw) -> FinancialConfigLike:
    base = dict(
        payday_day=28,
        net_monthly_income_minor=250_000,
        flat_share_minor=60_000,
        buffer_minor=15_000,
        tax_setaside_mode="off",
        tax_setaside_fixed_minor=None,
    )
    base.update(kw)
    return FinancialConfigLike(**base)


def test_safe_to_spend_setup_missing_when_payday_unset():
    result = safe_to_spend(
        config=_config(payday_day=None),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
    )
    assert result.safe_to_spend_minor is None
    assert "payday_day" in result.setup_missing


def test_safe_to_spend_waterfall_sums_to_income_pence_exact():
    """docs/phases/PHASE-4-insights.md acceptance: the waterfall segments sum
    pence-exact to income."""
    result = safe_to_spend(
        config=_config(),
        today="2026-07-15",
        committed=[CommittedInput("Netflix", 999), CommittedInput("Gym", 2817)],
        rental_income_minor=0,
        goals=[GoalSetAsideInput("house_deposit", monthly_pledge_minor=100_000, required_per_month_minor=None, status="behind")],
        discretionary_spent_minor=40_000,
        annual_tax_estimate_minor=None,
    )
    assert result.setup_missing == []
    segments = (
        result.committed_minor
        + result.goal_set_aside_minor
        + result.tax_set_aside_minor
        + result.buffer_minor
        + result.spent_so_far_minor
        + result.remaining_minor
    )
    assert segments == result.income_minor == 250_000
    # committed = subs (3816) + flat share (60000, no dedup match)
    assert result.committed_minor == 999 + 2817 + 60_000
    assert result.goal_set_aside_minor == 100_000
    assert result.safe_to_spend_minor == 250_000 - result.committed_minor - 100_000 - 0 - 15_000


def test_safe_to_spend_dedups_flat_share_against_a_matching_recurring():
    """A recurring row whose monthly-equivalent matches the configured flat
    share counts once, not twice (docs/API.md §6a dedup)."""
    result = safe_to_spend(
        config=_config(flat_share_minor=60_000),
        today="2026-07-15",
        committed=[CommittedInput("Flat rent transfer", 60_000)],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
    )
    assert result.committed_minor == 60_000  # not 120_000


def test_goal_setaside_rule_pledge_and_deposit_required_only():
    result = safe_to_spend(
        config=_config(flat_share_minor=0),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[
            # unpledged deposit with a live trend → uses required_per_month
            GoalSetAsideInput("house_deposit", monthly_pledge_minor=None, required_per_month_minor=109_500, status="behind"),
            # rebuild, unpledged → rides on what's left (0)
            GoalSetAsideInput("t212_rebuild", monthly_pledge_minor=None, required_per_month_minor=None, status="no_trend"),
        ],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
    )
    assert result.goal_set_aside_minor == 109_500


def test_goal_setaside_deposit_no_trend_and_unpledged_contributes_nothing():
    result = safe_to_spend(
        config=_config(flat_share_minor=0),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[GoalSetAsideInput("house_deposit", monthly_pledge_minor=None, required_per_month_minor=109_500, status="no_trend")],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=None,
    )
    assert result.goal_set_aside_minor == 0


def test_auto_tax_setaside_divides_estimate_over_months_to_january():
    result = safe_to_spend(
        config=_config(flat_share_minor=0, tax_setaside_mode="auto"),
        today="2026-07-15",  # 6 months to next 31 Jan
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=0,
        annual_tax_estimate_minor=60_000,
    )
    assert result.tax_set_aside_minor == 10_000  # ceil(60000 / 6)


def test_negative_remaining_is_reported_honestly():
    result = safe_to_spend(
        config=_config(flat_share_minor=0),
        today="2026-07-15",
        committed=[],
        rental_income_minor=0,
        goals=[],
        discretionary_spent_minor=999_999,  # spent far more than safe
        annual_tax_estimate_minor=None,
    )
    assert result.remaining_minor < 0
    assert result.per_day_remaining_minor < 0  # never flattered to 0


# ===================================================================== §6b
def test_month_summary_shapes_categories_and_ships_methodology_note():
    summary = month_summary(
        month="2026-07",
        income_minor=250_000,
        categories=[
            CategoryMonthInput("groceries", "Groceries", 2, spend_minor=48_000, avg_3mo_minor=47_000, prev_avg_3mo_minor=40_000),
            CategoryMonthInput("eating_out", "Eating out", 3, spend_minor=10_000, avg_3mo_minor=11_000, prev_avg_3mo_minor=9_000),
        ],
    )
    assert summary["spend_minor"] == 58_000
    assert summary["net_minor"] == 250_000 - 58_000
    assert summary["categories"][0]["key"] == "groceries"  # ordered by spend desc
    groceries = summary["categories"][0]
    assert groceries["benchmark"]["band"] == "above_average"  # 47_000 > 45_000
    assert groceries["share_pct"] == round(48_000 / 58_000 * 100, 1)
    assert "roughly typical" in summary["methodology_note"].lower()


# ===================================================================== §6c
def test_tip_category_trending_up_fires_and_does_not():
    fires = tip_category_trending_up(
        [{"label": "Eating out", "avg_3mo_minor": 20_000, "prev_avg_3mo_minor": 15_000}]
    )
    assert fires is not None
    assert "20,000" not in fires.body  # formatted as money, not raw pence
    assert "£200.00" in fires.body and "£150.00" in fires.body
    # under the 20% ratio → no tip
    assert tip_category_trending_up([{"label": "Eating out", "avg_3mo_minor": 20_000, "prev_avg_3mo_minor": 19_000}]) is None


def test_tip_cancel_candidates_fires_and_does_not():
    fires = tip_cancel_candidates([{"label": "OldApp", "monthly_equivalent_minor": 799}])
    assert fires is not None
    assert "worth checking you still use this" in fires.body.lower()
    assert tip_cancel_candidates([]) is None


def test_tip_price_rises_fires_and_does_not():
    fires = tip_price_rises([{"label": "Spotify", "old_minor": 999, "new_minor": 1199, "drift_pct": 20.0}])
    assert fires is not None
    assert "£9.99" in fires.body and "£11.99" in fires.body
    assert tip_price_rises([{"label": "Spotify", "old_minor": 999, "new_minor": 1049, "drift_pct": 5.0}]) is None


def test_tip_discretionary_variance_fires_and_does_not():
    fires = tip_discretionary_variance([10_000, 60_000, 12_000, 55_000, 8_000, 62_000])
    assert fires is not None
    steady = tip_discretionary_variance([30_000, 31_000, 29_000, 30_500, 30_000, 29_500])
    assert steady is None


def test_tip_emergency_fund_low_fires_and_does_not():
    fires = tip_emergency_fund_low(accessible_cash_minor=200_000, essential_monthly_minor=100_000)
    assert fires is not None
    assert "trade-off" in fires.body.lower()
    assert tip_emergency_fund_low(accessible_cash_minor=400_000, essential_monthly_minor=100_000) is None


def test_tip_tax_setaside_gap_fires_and_does_not():
    assert tip_tax_setaside_gap(has_tax_estimate=True, setaside_mode="off") is not None
    assert tip_tax_setaside_gap(has_tax_estimate=True, setaside_mode="auto") is None
    assert tip_tax_setaside_gap(has_tax_estimate=False, setaside_mode="off") is None


def test_tip_sa_registration_deadline_fires_and_does_not():
    fires = tip_sa_registration_deadline(registered_for_sa=None, has_rental_activity=True, today="2026-07-10")
    assert fires is not None
    assert "5 october 2026" in fires.body.lower()
    # registered → nothing to nudge
    assert tip_sa_registration_deadline(registered_for_sa=1, has_rental_activity=True, today="2026-07-10") is None
    # no rental → not applicable
    assert tip_sa_registration_deadline(registered_for_sa=None, has_rental_activity=False, today="2026-07-10") is None
    # outside the [1 Jul, 5 Oct] window
    assert tip_sa_registration_deadline(registered_for_sa=None, has_rental_activity=True, today="2026-11-01") is None


def test_no_tip_body_uses_forbidden_words_or_exclamations():
    """docs/phases/PHASE-4-insights.md acceptance: copy audit — no
    'overspending', no 'warning', no exclamation marks (DESIGN §6)."""
    tips = [
        tip_category_trending_up([{"label": "Eating out", "avg_3mo_minor": 20_000, "prev_avg_3mo_minor": 15_000}]),
        tip_cancel_candidates([{"label": "OldApp", "monthly_equivalent_minor": 799}]),
        tip_price_rises([{"label": "Spotify", "old_minor": 999, "new_minor": 1199, "drift_pct": 20.0}]),
        tip_discretionary_variance([10_000, 60_000, 12_000, 55_000, 8_000, 62_000]),
        tip_emergency_fund_low(200_000, 100_000),
        tip_tax_setaside_gap(True, "off"),
        tip_sa_registration_deadline(None, True, "2026-07-10"),
    ]
    for tip in tips:
        assert tip is not None
        text = f"{tip.title} {tip.body}".lower()
        assert "overspending" not in text
        assert "warning" not in text
        assert "!" not in f"{tip.title}{tip.body}"
