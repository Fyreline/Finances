"""Emergency-fund adequacy check — docs/PLAN.md §4 S2, docs/phases/
PHASE-9-personal-goals.md §2. Pure function; every band, including the
lowest, reads as calm information (docs/PLAN.md §6 rule 8 "no guilt UI") —
a low reading explicitly allows for a deliberate trade-off while saving
toward another goal (e.g. the house deposit), never a failing.
"""
from __future__ import annotations

_MONTHS_BUILDING = 1.0  # < this: "building from scratch"
_MONTHS_GUIDE = 3.0  # [BUILDING, this): "below the usual 3-6 month guide"
_MONTHS_WELL = 6.0  # [GUIDE, this): "within the usual range"; >= this: "well covered"

_TRADE_OFF_NOTE = " That can be a deliberate trade-off while you're saving toward other goals, not a mistake."


def emergency_fund_check(
    accessible_cash_minor: int,
    essential_monthly_minor: int,
    has_active_savings_goal: bool,
) -> dict:
    """`accessible_cash_minor` = net worth of `kind IN ('current','savings')`
    accounts only (investments excluded — docs/phases/PHASE-9 §2).
    `essential_monthly_minor` <= 0 (no spending history yet) yields an
    honest `unknown` verdict rather than a divide-by-zero or a fabricated
    number (docs/PLAN.md §6 rule 8, ARCHITECTURE.md §6 "never guesses").
    `has_active_savings_goal` — true when a house-deposit/rebuild-style goal
    is active and behind — appends the deliberate-trade-off sentence to the
    two lower bands only (docs/phases/PHASE-9 §2's "deliberate copy point")."""
    if essential_monthly_minor <= 0:
        return {
            "months_of_cover": None,
            "verdict": "unknown",
            "copy": "Not enough spending history yet to estimate essential monthly costs.",
        }

    months = round(accessible_cash_minor / essential_monthly_minor, 1)
    trade_off = _TRADE_OFF_NOTE if has_active_savings_goal else ""

    if months < _MONTHS_BUILDING:
        verdict = "building_from_scratch"
        copy = f"Accessible cash covers about {months} months of essential spending — building up from scratch." + trade_off
    elif months < _MONTHS_GUIDE:
        verdict = "below_guide"
        copy = (
            f"Accessible cash covers about {months} months of essential spending, "
            f"below the usual 3-6 month guide." + trade_off
        )
    elif months < _MONTHS_WELL:
        verdict = "within_range"
        copy = f"Accessible cash covers about {months} months of essential spending, within the usual range."
    else:
        verdict = "well_covered"
        copy = f"Accessible cash covers about {months} months of essential spending — well covered."

    return {"months_of_cover": months, "verdict": verdict, "copy": copy}
