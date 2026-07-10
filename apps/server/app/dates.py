"""Calendar/tax-year date helpers — Europe/London, not UTC (docs/ARCHITECTURE.md
§4: "a transaction at 23:30 BST on the 31st belongs to that month, not UTC's
next one"). Every month/tax-year boundary in the codebase goes through these
two functions; no ad-hoc ``datetime.now()`` elsewhere.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")

_DATE_FMT = "%Y-%m-%d"


def now_london() -> datetime:
    """The current moment, expressed in Europe/London local time."""
    return datetime.now(timezone.utc).astimezone(LONDON)


def to_local_date(dt: datetime) -> str:
    """Convert a datetime (aware or naive-assumed-UTC — provider timestamps
    are always UTC, docs/DATA_MODEL.md §2) to its Europe/London calendar date
    as ``"YYYY-MM-DD"``. Handles the BST offset, so a transaction stamped
    23:30 UTC in summer (00:30 BST, the next UK day) or 23:30 UTC in winter
    (23:30 GMT, the same UK day) resolve correctly — this is the one thing
    that must never be done with naive UTC date-slicing.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON).strftime(_DATE_FMT)


def tax_year_of(local_date: str) -> str:
    """The UK tax year (6 Apr–5 Apr) containing a Europe/London calendar date
    string ``"YYYY-MM-DD"``, returned as ``"YYYY-YY"`` e.g. ``"2025-26"``
    (docs/DATA_MODEL.md §6). 5 April belongs to the ENDING year's tax year;
    6 April starts the next one — the exact statutory boundary.
    """
    d = datetime.strptime(local_date, _DATE_FMT).date()
    start_year = d.year if (d.month, d.day) >= (4, 6) else d.year - 1
    end_short = (start_year + 1) % 100
    return f"{start_year}-{end_short:02d}"


def tax_year_bounds(tax_year_key: str) -> tuple[str, str]:
    """Inverse of tax_year_of: ``"2025-26"`` -> ``("2025-04-06", "2026-04-05")``."""
    start_year = int(tax_year_key.split("-")[0])
    start = date(start_year, 4, 6)
    end = date(start_year + 1, 4, 5)
    return start.strftime(_DATE_FMT), end.strftime(_DATE_FMT)
