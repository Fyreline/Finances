"""app/engines/goals.py — pure projection maths, docs/DATA_MODEL.md §4a.

The pinned worked example below uses the doc's own generic placeholder
figures (T=£10,000, B=£1,000, t=2026-07-10, D=2027-01-10) — never the real
target/baseline/deadline, which live only in docs/PRIVATE.md (gitignored)
and local runtime config, per that file's redaction scheme
(docs/HANDOFF.md "Decisions").
"""
from __future__ import annotations

from app.engines.goals import (
    month_end_deltas,
    months_remaining,
    project_goal,
    required_per_month_minor,
    trend_per_month_minor,
)

# ------------------------------------------------------------- months_remaining
def test_months_remaining_pinned_placeholder_example():
    assert months_remaining("2026-07-10", "2027-01-10") == 6


def test_months_remaining_zero_when_deadline_already_passed():
    assert months_remaining("2026-07-10", "2026-07-01") == 0


def test_months_remaining_zero_when_deadline_is_today():
    assert months_remaining("2026-07-10", "2026-07-10") == 0


def test_months_remaining_counts_a_month_end_in_the_evaluation_months_own_month():
    """A month-end strictly after `t`, even within `t`'s own calendar month,
    counts (docs/DATA_MODEL.md §4a)."""
    assert months_remaining("2026-07-10", "2026-07-31") == 1


# --------------------------------------------------------- required_per_month
def test_required_per_month_pinned_placeholder_example():
    # T=£10,000, B=£1,000 -> diff £9,000 over 6 months -> £1,500/month
    assert required_per_month_minor(1_000_000, 100_000, 6) == 150_000


def test_required_per_month_ceils_never_flatters():
    # diff of 100p over 3 months = 33.33... -> ceils to 34p, never 33p
    assert required_per_month_minor(1000, 900, 3) == 34


def test_required_per_month_zero_once_target_already_met():
    assert required_per_month_minor(1000, 1500, 6) == 0


def test_required_per_month_whole_shortfall_due_now_when_no_months_left():
    assert required_per_month_minor(1000, 400, 0) == 600


# ------------------------------------------------------------- month_end_deltas
def test_month_end_deltas_empty_with_fewer_than_two_snapshots():
    assert month_end_deltas([]) == []
    assert month_end_deltas([("2026-07-31", 100_000)]) == []


def test_month_end_deltas_median_of_three_trend():
    series = [
        ("2026-05-31", 100_000),
        ("2026-06-30", 190_000),  # +90,000
        ("2026-07-31", 280_000),  # +90,000
    ]
    deltas = month_end_deltas(series)
    assert deltas == [90_000, 90_000]
    assert trend_per_month_minor(deltas) == 90_000


def test_month_end_deltas_use_latest_snapshot_on_or_before_the_real_month_end():
    """Snapshots need not land exactly on the last calendar day — the
    latest one on/before each month's real last day represents that month
    (docs/DATA_MODEL.md §4a)."""
    series = [
        ("2026-05-29", 100_000),
        ("2026-06-28", 190_000),
        ("2026-07-30", 280_000),
    ]
    assert month_end_deltas(series) == [90_000, 90_000]


def test_month_end_deltas_only_last_three_feed_the_trend():
    series = [
        ("2026-01-31", 0),
        ("2026-02-28", 500_000),  # +500,000 (outlier, must fall out of the last-3 window)
        ("2026-03-31", 520_000),  # +20,000
        ("2026-04-30", 540_000),  # +20,000
        ("2026-05-31", 560_000),  # +20,000
    ]
    deltas = month_end_deltas(series)
    assert deltas == [500_000, 20_000, 20_000, 20_000]
    assert trend_per_month_minor(deltas) == 20_000


def test_trend_per_month_median_of_two_averages():
    # Even-length window (only 2 deltas available yet): median = average.
    assert trend_per_month_minor([5_000, 6_000]) == 5_500


# ------------------------------------------------------------------ project_goal
def test_project_goal_pinned_placeholder_example_first_render_no_trend_yet():
    """The pinned worked example: no snapshot history yet — required_per_month
    is still £1,500 (docs/DATA_MODEL.md §4a "the dashboard's first render
    should show the equivalent computed figure"); status is `no_trend` since
    fewer than 2 month-end snapshots exist."""
    projection = project_goal(
        target_minor=1_000_000,
        target_date="2027-01-10",
        current_minor=100_000,
        eval_date="2026-07-10",
        deltas=[],
    )
    assert projection.months_remaining == 6
    assert projection.required_per_month_minor == 150_000
    assert projection.status == "no_trend"
    assert projection.trend_per_month_minor is None
    assert projection.catch_up_per_month_minor is None


def test_project_goal_behind_status_with_trending_snapshots():
    """docs/phases/PHASE-3-t212-goals.md acceptance: three faked month-end
    snapshots trending £900/month -> status `behind`, catch_up equals
    ceil((T-B)/m) — same value as required_per_month."""
    deltas = [90_000, 90_000]  # £900/month trend
    projection = project_goal(
        target_minor=2_000_000,  # far beyond what this trend reaches in the time left
        target_date="2027-01-10",  # m=6, per the pinned placeholder example
        current_minor=280_000,
        eval_date="2026-07-10",
        deltas=deltas,
    )
    assert projection.status == "behind"
    assert projection.trend_per_month_minor == 90_000
    assert projection.catch_up_per_month_minor is not None
    assert projection.catch_up_per_month_minor == projection.required_per_month_minor


def test_project_goal_on_track_when_projection_meets_target():
    deltas = [200_000, 200_000, 200_000]
    projection = project_goal(
        target_minor=1_000_000,
        target_date="2026-12-31",
        current_minor=400_000,
        eval_date="2026-07-10",
        deltas=deltas,
    )
    assert projection.status == "on_track"
    assert projection.catch_up_per_month_minor is None
    assert projection.required_per_month_minor is not None


def test_project_goal_open_ended_goal_has_no_target_maths():
    """t212_rebuild: target_minor/target_date are NULL (open-ended) — trend
    still computes for its chart, but there's no required/projected/verdict
    (docs/DATA_MODEL.md §4)."""
    projection = project_goal(
        target_minor=None,
        target_date=None,
        current_minor=42_000,
        eval_date="2026-07-10",
        deltas=[5_000, 6_000],
    )
    assert projection.required_per_month_minor is None
    assert projection.months_remaining is None
    assert projection.projected_at_target_minor is None
    assert projection.status == "no_trend"
    assert projection.trend_per_month_minor == 5_500
    assert projection.catch_up_per_month_minor is None


def test_project_goal_open_ended_goal_no_trend_when_no_deltas_either():
    projection = project_goal(
        target_minor=None, target_date=None, current_minor=30_000, eval_date="2026-07-10", deltas=[]
    )
    assert projection.status == "no_trend"
    assert projection.trend_per_month_minor is None
