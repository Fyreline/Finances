"""``tax_years`` seeding/ensuring helpers — docs/DATA_MODEL.md §6.

A ``tax_years`` row is just the 6 Apr–5 Apr window for a key like ``2026-27``;
:func:`ensure_tax_year` derives its bounds from ``dates.tax_year_bounds`` so the
window is never hand-typed. Idempotent — safe to call on every startup and from
the mail pipeline as new years appear.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .dates import tax_year_bounds
from .models import TaxYear

# The first affected SA year is 2025-26 (letting began mid-2025, docs/TAX.md
# §1); 2026-27 is the current/live year the dashboard shows. Both are seeded on
# startup so the TaxPage and estimate have their year rows from first boot.
SEED_TAX_YEARS = ("2025-26", "2026-27")


def ensure_tax_year(session: Session, tax_year: str) -> TaxYear:
    """Return the ``tax_years`` row for ``tax_year``, creating it (with bounds
    derived from the key) if absent. Commits only when it inserts."""
    row = session.get(TaxYear, tax_year)
    if row is not None:
        return row
    start, end = tax_year_bounds(tax_year)
    row = TaxYear(key=tax_year, start_date=start, end_date=end)
    session.add(row)
    session.commit()
    return row


def seed_tax_years(session: Session) -> None:
    """Idempotent upsert of the base tax years (docs/DATA_MODEL.md §6) — safe on
    every startup, same discipline as ``seed_categories``."""
    for key in SEED_TAX_YEARS:
        ensure_tax_year(session, key)
