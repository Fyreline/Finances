"""app/engines/benchmarks.py — heuristic spending bands, docs/API.md §6b.

The bands are deliberately illustrative (generic ONS-derived household
averages, never the user's real figures — docs/PRIVATE.md). These tests pin
the verdict boundaries and the DESIGN §6 kraft-vs-crimson (`severe`) split.
"""
from __future__ import annotations

from app.engines.benchmarks import BANDS, METHODOLOGY_NOTE, benchmark_for


def test_no_benchmark_for_unbanded_category():
    assert benchmark_for("housing", 100_000) is None
    assert benchmark_for("salary", 100_000) is None


def test_maintainable_average_above_boundaries():
    band = BANDS["groceries"]  # (32_000, 45_000)
    assert benchmark_for("groceries", band.maintainable_max_minor).band == "maintainable"
    assert benchmark_for("groceries", band.maintainable_max_minor + 1).band == "average"
    assert benchmark_for("groceries", band.average_max_minor).band == "average"
    assert benchmark_for("groceries", band.average_max_minor + 1).band == "above_average"


def test_twenty_five_percent_over_band_is_above_average_but_not_severe():
    """docs/phases/PHASE-4-insights.md acceptance: a category 25% over its band
    shows `above_average` in kraft (not crimson) — i.e. not `severe`."""
    band = BANDS["eating_out"]  # average_max 22_000
    avg_3mo = round(band.average_max_minor * 1.25)  # 25% over
    verdict = benchmark_for("eating_out", avg_3mo)
    assert verdict.band == "above_average"
    assert verdict.severe is False  # kraft, not crimson (only past 1.5×)


def test_severe_only_past_1_5x_band():
    band = BANDS["eating_out"]
    verdict = benchmark_for("eating_out", round(band.average_max_minor * 1.6))
    assert verdict.severe is True


def test_verdict_carries_bounds_and_dated_source():
    verdict = benchmark_for("groceries", 30_000)
    assert verdict.band_bounds_minor == (32_000, 45_000)
    assert verdict.as_of  # a real as-of date ships for the tooltip
    assert "heuristic" in verdict.source.lower()


def test_methodology_note_is_explicitly_heuristic():
    lowered = METHODOLOGY_NOTE.lower()
    assert "roughly typical" in lowered
    assert "not" in lowered and "statistical truth" in lowered
    assert "!" not in METHODOLOGY_NOTE  # calm tone (DESIGN §6)
