"""app/models.py — table creation + category seed (docs/DATA_MODEL.md §3,
docs/phases/PHASE-1-scaffold.md item 2).
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import CATEGORY_SEED, Category


def test_categories_seeded_on_startup(client):
    """The `client` fixture boots the app (lifespan runs), which seeds
    categories — verifies the full taxonomy landed with viz_slots intact."""
    with SessionLocal() as session:
        rows = {c.key: c for c in session.scalars(select(Category)).all()}
    assert len(rows) == len(CATEGORY_SEED)
    for key, label, kind, viz_slot, _sort in CATEGORY_SEED:
        row = rows[key]
        assert row.label == label
        assert row.kind == kind
        assert row.viz_slot == viz_slot


def test_income_and_transfer_categories_have_no_viz_slot(client):
    with SessionLocal() as session:
        salary = session.scalar(select(Category).where(Category.key == "salary"))
        rental_income = session.scalar(select(Category).where(Category.key == "rental_income"))
    assert salary.viz_slot is None
    assert rental_income.viz_slot is None


def test_housing_and_bills_share_viz_slot_1(client):
    """docs/DESIGN.md §2b: 'housing & bills (the big fixed block)' is one slot."""
    with SessionLocal() as session:
        housing = session.scalar(select(Category).where(Category.key == "housing"))
        bills = session.scalar(select(Category).where(Category.key == "bills"))
    assert housing.viz_slot == bills.viz_slot == 1
