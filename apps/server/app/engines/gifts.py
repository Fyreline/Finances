"""Gift-occasion budget rollup — docs/PLAN.md §3 row 10, docs/phases/
PHASE-9-personal-goals.md §4. Pure function only; the occasion's `limit_minor`
is 100% user-set and never invented — `None` reports `no_limit_set`, never a
fabricated £0 cap (docs/PRIVATE.md "no limit figure given yet, don't invent
one"). Over-limit is calm information, not guilt (docs/PLAN.md §6 rule 8).
"""
from __future__ import annotations


def occasion_summary(limit_minor: int | None, item_prices_minor: list[int]) -> dict:
    """`item_prices_minor`: every item's price in the occasion, bought or
    still-planned — the whole intended spend counts toward the limit, not
    just what's already been bought (docs/phases/PHASE-9 §4 "items add up
    against the limit"). Zero items is a valid, non-crashing input (the
    fresh-occasion acceptance case)."""
    spent = sum(item_prices_minor)
    if limit_minor is None:
        return {"spent_minor": spent, "limit_minor": None, "remaining_minor": None, "verdict": "no_limit_set"}
    remaining = limit_minor - spent
    verdict = "over_limit" if remaining < 0 else "under_limit"
    return {"spent_minor": spent, "limit_minor": limit_minor, "remaining_minor": remaining, "verdict": verdict}
