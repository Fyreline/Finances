"""app/dates.py — Europe/London day boundary + UK tax-year boundary
(docs/phases/PHASE-1-scaffold.md item 1: "unit-test the 5/6 Apr and
BST-midnight boundaries now, everything later leans on them").
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.dates import tax_year_bounds, tax_year_of, to_local_date


# --------------------------------------------------------------------------
# to_local_date — BST-midnight boundary
# --------------------------------------------------------------------------
def test_to_local_date_bst_pushes_late_utc_evening_into_next_uk_day():
    # 23:30 UTC on 30 Jun = 00:30 BST on 1 Jul — the local UK date is the 1st,
    # not the 30th (BST is UTC+1 in summer).
    dt = datetime(2026, 6, 30, 23, 30, tzinfo=timezone.utc)
    assert to_local_date(dt) == "2026-07-01"


def test_to_local_date_gmt_winter_matches_utc_date():
    # In winter (GMT = UTC+0) there's no shift.
    dt = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    assert to_local_date(dt) == "2026-01-15"


def test_to_local_date_bst_morning_stays_same_uk_day():
    # 09:00 UTC in July = 10:00 BST, still the same calendar day.
    dt = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
    assert to_local_date(dt) == "2026-07-10"


def test_to_local_date_accepts_naive_datetime_as_utc():
    dt = datetime(2026, 6, 30, 23, 30)  # naive — assumed UTC
    assert to_local_date(dt) == "2026-07-01"


# --------------------------------------------------------------------------
# tax_year_of — 5/6 April statutory boundary
# --------------------------------------------------------------------------
def test_tax_year_of_5_april_belongs_to_ending_year():
    assert tax_year_of("2026-04-05") == "2025-26"


def test_tax_year_of_6_april_starts_next_tax_year():
    assert tax_year_of("2026-04-06") == "2026-27"


def test_tax_year_of_mid_year_date():
    assert tax_year_of("2026-07-10") == "2026-27"


def test_tax_year_of_first_affected_year():
    # Letting began partway through 2025-26 (see docs/PRIVATE.md) — first SA year.
    assert tax_year_of("2025-09-15") == "2025-26"


def test_tax_year_bounds_round_trips():
    start, end = tax_year_bounds("2025-26")
    assert start == "2025-04-06"
    assert end == "2026-04-05"
    assert tax_year_of(start) == "2025-26"
    assert tax_year_of(end) == "2025-26"
