"""The affordability check — docs/PLAN.md §3 row 11 (refined), docs/phases/
PHASE-9-personal-goals.md §5. The core new mechanic this phase adds: not a
capped-pot budget, a live go/no-go check composed from two already-computed
figures — Phase 4's safe-to-spend headroom and Phase 3's goal projection
maths, run once with the item's price and once without. Pure function, no
I/O, no new money model (docs/ARCHITECTURE.md §3). Same function powers goal
10's gift items (an occasion's remaining budget stands in for the general
safe-to-spend headroom, docs/phases/PHASE-9 §4 "share the mechanic ... don't
build two separate systems") — `goal_projection_before`/`_after` are simply
`None` in that case, since a gift item doesn't touch a savings goal.
"""
from __future__ import annotations

from math import ceil

from .goals import GoalProjection

_WEEKS_PER_MONTH = 52 / 12


def check_affordability(
    price_minor: int,
    safe_to_spend_headroom_minor: int | None,
    goal_projection_before: GoalProjection | None,
    goal_projection_after: GoalProjection | None,
) -> dict:
    """`safe_to_spend_headroom_minor` — this period's remaining safe-to-spend
    (or an occasion's remaining budget for a gift item), `None` while unset.
    `goal_projection_before`/`_after` — `engines.goals.project_goal` run with
    the goal's current balance unchanged / reduced by `price_minor`, `None`
    when there is no relevant active goal to check against. Returns
    `{verdict, detail}`:

    - `fits_now` — the price fits within this period's spare cash outright,
      no goal involved.
    - `not_yet` — it would plausibly come out of savings instead, and doing
      so would meaningfully delay an active goal (on_track -> behind, or a
      bigger catch-up if already behind); `detail` estimates the delay in
      weeks from the goal's own trend when one exists (docs/ARCHITECTURE.md
      §6 "never flatters" — the estimate ceils, so it never understates the
      delay).
    - `fits_from_spare_cash` — exceeds this period's headroom but wouldn't
      meaningfully hurt a goal if saved up for rather than funded from
      savings right now.
    - `unknown` — neither a headroom figure nor a goal exists yet to check
      against (fresh setup state, docs/phases/PHASE-9 acceptance list).
    """
    if safe_to_spend_headroom_minor is None and goal_projection_before is None:
        return {"verdict": "unknown", "detail": "Not enough set up yet to check affordability here."}

    if safe_to_spend_headroom_minor is not None and price_minor <= safe_to_spend_headroom_minor:
        return {"verdict": "fits_now", "detail": "Yes, this fits within what's currently available."}

    if goal_projection_before is not None and goal_projection_after is not None:
        if _meaningfully_delayed(goal_projection_before, goal_projection_after):
            weeks = _delay_weeks(price_minor, goal_projection_before)
            if weeks:
                detail = (
                    f"Not yet — funding this from savings would push the goal back roughly "
                    f"{weeks} week{'s' if weeks != 1 else ''}."
                )
            else:
                detail = "Not yet — funding this from savings would push the goal back."
            return {"verdict": "not_yet", "detail": detail}
        # A goal exists but wouldn't be meaningfully affected — safe to
        # stretch to a future period rather than raid savings today.
        return {
            "verdict": "fits_from_spare_cash",
            "detail": "Exceeds what's currently available, but wouldn't meaningfully affect the savings goal if it came from there instead.",
        }

    return {
        "verdict": "fits_from_spare_cash",
        "detail": "Exceeds what's currently available right now — would fit with a bit more headroom.",
    }


def _meaningfully_delayed(before: GoalProjection, after: GoalProjection) -> bool:
    if before.status == "on_track" and after.status == "behind":
        return True
    if before.status == "behind" and after.status == "behind":
        before_catchup = before.catch_up_per_month_minor or 0
        after_catchup = after.catch_up_per_month_minor or 0
        return after_catchup > before_catchup
    return False


def _delay_weeks(price_minor: int, before: GoalProjection) -> int | None:
    """`None` when there's no positive trend to estimate a delay from —
    never inventing a number (docs/ARCHITECTURE.md §6)."""
    trend = before.trend_per_month_minor
    if not trend or trend <= 0:
        return None
    months = price_minor / trend
    return ceil(months * _WEEKS_PER_MONTH)
