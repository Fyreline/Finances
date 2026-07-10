"""Goal projection maths — docs/DATA_MODEL.md §4a, pure functions only (no
I/O; `routers/goals.py` assembles the snapshot rows and calls these,
docs/ARCHITECTURE.md §3 "Engines are pure functions over rows + config").

The pinned worked example in `tests/test_goals_engine.py` uses the doc's own
generic placeholder figures (T=£10,000, B=£1,000, t=2026-07-10, D=2027-01-10)
— never the real target/baseline/deadline, which live only in
docs/PRIVATE.md (gitignored) and local runtime config, per that file's
redaction scheme (docs/HANDOFF.md "Decisions").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

_DATE_FMT = "%Y-%m-%d"


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, _DATE_FMT).date()


def _month_end_date(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def months_remaining(t: str | date, d: str | date) -> int:
    """Count of month-ends in `(t, D]` (docs/DATA_MODEL.md §4a) — a
    month-end that falls strictly after `t`, even within `t`'s own calendar
    month, counts; `D` itself counts if it is exactly a month-end (the usual
    case for a goal deadline). Returns 0 if `d <= t`."""
    t_date = _parse_date(t)
    d_date = _parse_date(d)
    if d_date <= t_date:
        return 0

    count = 0
    year, month = t_date.year, t_date.month
    while True:
        month_end = _month_end_date(year, month)
        if month_end > t_date:
            if month_end > d_date:
                break
            count += 1
            if month_end == d_date:
                break
        year, month = _next_month(year, month)
    return count


def required_per_month_minor(target_minor: int, current_minor: int, months: int) -> int:
    """`ceil((T - B) / m)`, in integer pence — ceiling, never flatters
    (docs/ARCHITECTURE.md §6 "percentages ... rounds against the user").
    0 once the target is already met (or over-met); if `months <= 0` the
    whole shortfall is due now."""
    diff = target_minor - current_minor
    if diff <= 0:
        return 0
    if months <= 0:
        return diff
    return -(-diff // months)  # integer ceiling division


def month_end_deltas(series: list[tuple[str, int]]) -> list[int]:
    """`series`: ascending `(local_date, balance_minor)` pairs at *any*
    cadence (daily sync snapshots need not land exactly on a month's last
    day). Resolves one representative balance per calendar month present —
    the latest snapshot on or before that month's real last day — then
    returns the deltas between consecutive resolved months, oldest first
    (docs/DATA_MODEL.md §4a "median of last 3 month-end deltas"). Needs at
    least two distinct resolved months to produce any delta at all."""
    if len(series) < 2:
        return []
    parsed = sorted((_parse_date(d), v) for d, v in series)
    months = sorted({(d.year, d.month) for d, _ in parsed})

    monthly_values: list[int] = []
    idx = 0
    last_seen: int | None = None
    for year, month in months:
        boundary = _month_end_date(year, month)
        while idx < len(parsed) and parsed[idx][0] <= boundary:
            last_seen = parsed[idx][1]
            idx += 1
        if last_seen is not None:
            monthly_values.append(last_seen)

    return [monthly_values[i] - monthly_values[i - 1] for i in range(1, len(monthly_values))]


def trend_per_month_minor(deltas: list[int]) -> int | None:
    """Median of the last 3 month-end deltas — one odd month can't lie
    (docs/DATA_MODEL.md §4a). `None` with zero deltas."""
    if not deltas:
        return None
    return round(median(deltas[-3:]))


@dataclass
class GoalProjection:
    months_remaining: int | None
    required_per_month_minor: int | None
    trend_per_month_minor: int | None
    projected_at_target_minor: int | None
    status: str  # 'on_track' | 'behind' | 'no_trend'
    catch_up_per_month_minor: int | None


def project_goal(
    *,
    target_minor: int | None,
    target_date: str | None,
    current_minor: int,
    eval_date: str,
    deltas: list[int],
) -> GoalProjection:
    """The whole of docs/DATA_MODEL.md §4a in one function. `target_minor`/
    `target_date` both `None` means an open-ended goal (t212_rebuild) — its
    trend still computes (for the rebuild chart) but there is no
    required/projected/on-track verdict to give, so status is always
    `no_trend` for it. `deltas` come from :func:`month_end_deltas` — fewer
    than 2 month-end snapshots yields an empty list, and `required_per_month`
    is still reported (from `target`/`current`/`months` alone) even with no
    trend yet, matching "the dashboard's first render should show the
    equivalent computed figure for the real, locally-configured goal"."""
    has_target = target_minor is not None and target_date is not None
    months = months_remaining(eval_date, target_date) if has_target else None
    required = (
        required_per_month_minor(target_minor, current_minor, months) if has_target and months is not None else None
    )

    if not deltas:
        return GoalProjection(
            months_remaining=months,
            required_per_month_minor=required,
            trend_per_month_minor=None,
            projected_at_target_minor=None,
            status="no_trend",
            catch_up_per_month_minor=None,
        )

    trend = trend_per_month_minor(deltas)

    if not has_target or months is None:
        return GoalProjection(
            months_remaining=None,
            required_per_month_minor=None,
            trend_per_month_minor=trend,
            projected_at_target_minor=None,
            status="no_trend",
            catch_up_per_month_minor=None,
        )

    assert trend is not None  # deltas is non-empty, so trend_per_month_minor cannot be None here
    projected = current_minor + trend * months
    if projected >= target_minor:
        return GoalProjection(months, required, trend, projected, "on_track", None)
    return GoalProjection(months, required, trend, projected, "behind", required)
