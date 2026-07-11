"""app/schema_sync.py — the auto-migration safety net added 2026-07-11 after
`financial_config`/`tax_config` each shipped a new nullable column that never
got added to the already-existing prod database, 500ing every endpoint that
touched them (docs/HANDOFF.md "Production incident"/Phase 10 entries).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from app.models import Base
from app.schema_sync import SchemaSyncError, sync_schema


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'schema_sync_test.db'}")
    yield eng
    eng.dispose()


def test_adds_a_missing_nullable_column(engine):
    """Mirrors the real 2026-07-11 incident exactly: build the full current
    schema, then simulate "this db predates a model change" by dropping a
    real, currently-nullable column back off `financial_config` — the same
    shape as a prod db that existed before Phase 9 added it."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE financial_config DROP COLUMN pension_contributing"))

    inspector = inspect(engine)
    cols_before = {c["name"] for c in inspector.get_columns("financial_config")}
    assert "pension_contributing" not in cols_before

    sync_schema(engine)

    inspector = inspect(engine)
    cols_after = {c["name"] for c in inspector.get_columns("financial_config")}
    assert "pension_contributing" in cols_after


def test_preserves_existing_rows_when_adding_a_column(engine):
    """The whole point is a safe, non-destructive ADD COLUMN — prove a row
    that existed before the sync survives it, with the new column NULL
    (never a guessed default — docs/PRIVATE.md's tri-state rule)."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE financial_config DROP COLUMN pension_contributing"))
        conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, mishka_user_id, created_at) "
                "VALUES (1, 'test@example.com', 'Test', 1, datetime('now'))"
            )
        )
        conn.execute(text("INSERT INTO financial_config (user_id, buffer_minor) VALUES (1, 15000)"))

    sync_schema(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT user_id, buffer_minor, pension_contributing FROM financial_config WHERE user_id = 1")
        ).one()
    assert row.user_id == 1
    assert row.buffer_minor == 15000
    assert row.pension_contributing is None


def test_noop_when_schema_already_matches(engine):
    """The common case (every normal boot) — must not error or touch
    anything when there's genuinely nothing to do."""
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    before = {t: set(c["name"] for c in inspector.get_columns(t)) for t in inspector.get_table_names()}

    sync_schema(engine)  # should be a complete no-op

    inspector = inspect(engine)
    after = {t: set(c["name"] for c in inspector.get_columns(t)) for t in inspector.get_table_names()}
    assert before == after


def test_refuses_to_guess_a_not_null_column(engine):
    """A NOT NULL column with no safe default needs a human backfill
    decision — this must stop boot loudly, never invent a value."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE financial_config DROP COLUMN buffer_minor"))
        # buffer_minor is `nullable=False, server_default=text("15000")` in
        # the real model — server_default doesn't change the ORM-level
        # `nullable` flag this check reads, so this exercises the same path
        # a genuinely-unsafe NOT NULL addition would.

    with pytest.raises(SchemaSyncError, match="financial_config.buffer_minor"):
        sync_schema(engine)
