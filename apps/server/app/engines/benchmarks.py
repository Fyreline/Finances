"""Spending benchmark bands — docs/API.md §6b, a *config* module, not a
computation. Pure data + one verdict function.

⚠️ HEURISTIC, NOT AUTHORITATIVE. These bands are **rough, agent-estimated
figures**, loosely anchored to ONS *Family Spending in the UK* (Living Costs
and Food Survey) averages for a two-adult, no-children household, then
adjusted downward/for-Scotland and a young-professional profile. They are
**approximate comparison bands, not statistical truth** — every figure the UI
renders from here MUST carry a visible "estimate" framing plus this module's
`source`/`as_of` (docs/API.md §6b, docs/DESIGN.md §4d, PLAN §6). They are not
copied verbatim from any single ONS table; do not present them as precise.

Source anchor (illustrative, not a precise citation of specific line items):
ONS, *Family Spending in the UK* workbook —
https://www.ons.gov.uk/peoplepopulationandcommunity/personalandhouseholdfinances/expenditure/bulletins/familyspendingintheuk/latest
`as_of` below records the release the initial numbers were eyeballed against.
⚠️ verify against the then-latest ONS release when real spending data exists;
re-tune each band and bump its `as_of` in the same commit.

Bands are monthly, integer pence, keyed by `categories.key`. A category with
no entry here simply has no benchmark (housing, salary, transfers, rental —
too variable or not "spend"). Two thresholds per category:

  maintainable_max_minor : at or under → verdict "maintainable"
  average_max_minor      : at or under → verdict "average"; above → "above_average"

The verdict compares the **trailing-3-month average** (so a single odd month
never flips it — docs/API.md §6b). Colour is the UI's call (kraft for
above_average, crimson only past 1.5× the average band — docs/DESIGN.md §6);
this module only names the band and hands back the bounds for the tooltip.
"""
from __future__ import annotations

from dataclasses import dataclass

# The single as-of date stamped onto every band + the methodology note. Bump
# it (and the figures) the day real ONS line items are reconciled in.
BENCHMARK_AS_OF = "2024-03"  # ONS FYE-2023 release era; ⚠️ verify (see header)
BENCHMARK_SOURCE = "ONS Family Spending in the UK (heuristic, agent-estimated)"

# The `methodology_note` shipped verbatim in every /summary/month response
# (docs/API.md §6b) — heuristic, approximate, never precise.
METHODOLOGY_NOTE = (
    "Benchmark bands are rough, agent-estimated figures loosely derived from "
    "ONS Family Spending (two-adult household), adjusted for Scotland and a "
    "young professional couple. They are approximate comparison bands, not "
    f"statistical truth — read them as roughly typical, not a target ({BENCHMARK_SOURCE}, "
    f"as of {BENCHMARK_AS_OF})."
)


@dataclass(frozen=True)
class Band:
    maintainable_max_minor: int
    average_max_minor: int


# Monthly, integer pence. Deliberately round, deliberately conservative —
# these are illustrative, not the user's real figures (docs/PRIVATE.md
# redaction scheme forbids inventing real-looking personal numbers; these are
# generic household averages, clearly labelled heuristic).
BANDS: dict[str, Band] = {
    "groceries": Band(32_000, 45_000),  # £320 / £450
    "eating_out": Band(12_000, 22_000),  # £120 / £220
    "transport": Band(18_000, 32_000),  # £180 / £320
    "fun": Band(8_000, 16_000),  # £80 / £160
    "subscriptions": Band(3_000, 6_000),  # £30 / £60
    "shopping": Band(12_000, 25_000),  # £120 / £250
    "bills": Band(18_000, 30_000),  # £180 / £300
    "holidays": Band(12_000, 25_000),  # £120 / £250
    "health": Band(3_000, 7_000),  # £30 / £70
    "gifts": Band(4_000, 10_000),  # £40 / £100
}

# past this multiple of the average band, DESIGN §6 allows crimson over kraft
SEVERE_MULTIPLE = 1.5


@dataclass(frozen=True)
class BenchmarkVerdict:
    band: str  # 'maintainable' | 'average' | 'above_average'
    band_bounds_minor: tuple[int, int]  # the "roughly typical" range for the tooltip
    source: str
    as_of: str
    severe: bool  # trailing-3mo avg > 1.5× average band → UI may use crimson


def benchmark_for(category_key: str, avg_3mo_minor: int) -> BenchmarkVerdict | None:
    """Verdict for a category from its trailing-3-month average spend, or None
    when no band exists for that category (docs/API.md §6b). `band_bounds_minor`
    is always the "roughly typical" [maintainable_max, average_max] range so
    the pill tooltip can show it regardless of which band the value lands in."""
    band = BANDS.get(category_key)
    if band is None:
        return None
    bounds = (band.maintainable_max_minor, band.average_max_minor)
    if avg_3mo_minor <= band.maintainable_max_minor:
        name = "maintainable"
    elif avg_3mo_minor <= band.average_max_minor:
        name = "average"
    else:
        name = "above_average"
    severe = avg_3mo_minor > band.average_max_minor * SEVERE_MULTIPLE
    return BenchmarkVerdict(
        band=name, band_bounds_minor=bounds, source=BENCHMARK_SOURCE, as_of=BENCHMARK_AS_OF, severe=severe
    )
