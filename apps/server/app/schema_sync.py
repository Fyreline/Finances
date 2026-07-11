"""Lightweight auto-migration: adds columns a model gained that the actual
SQLite file doesn't have yet. Runs once at startup, right after
``Base.metadata.create_all`` (which only ever creates missing *tables*, never
adds columns to a table that already exists — the gap that caused two real
outages on 2026-07-11, docs/HANDOFF.md's "Production incident" and Phase 10
entries: a new nullable column landed in a model, the code shipped, and
nothing ever told the already-existing prod `tax_config`/`financial_config`
tables about it until a request hit the missing column and the whole
endpoint 500'd).

Deliberately narrow, not a real migration framework (docs/ARCHITECTURE.md §4
still says "Alembic only if a breaking change ever demands it" — this doesn't
change that call): it only ever does the one safe, reversible thing a
missing *nullable* column needs — ``ALTER TABLE ... ADD COLUMN`` — and it
refuses to touch anything else. A genuinely breaking change (a new NOT NULL
column with no server default, a renamed/dropped column, a type change)
needs a human decision about backfill/data loss, so this deliberately raises
instead of guessing at one.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .models import Base

logger = logging.getLogger(__name__)


class SchemaSyncError(RuntimeError):
    """Raised when the DB is missing something this lightweight sync can't
    safely fix itself — stop the boot rather than run against a schema the
    code doesn't actually match."""


def sync_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                # create_all already handles a wholly-new table; nothing to
                # do here (and get_columns() below would just KeyError).
                continue

            actual_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in actual_columns:
                    continue
                if not column.nullable:
                    raise SchemaSyncError(
                        f"{table.name}.{column.name} is a new NOT NULL column with no automatic "
                        "backfill story — this needs a human migration decision (what value do "
                        "existing rows get?), not an auto-ALTER. Stopping boot rather than guessing."
                    )
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"))
                logger.warning(
                    "schema_sync: added missing column %s.%s (%s) — the model changed and this "
                    "database predates it. This is a safety net, not a substitute for running the "
                    "real migration deliberately when you know a column is coming.",
                    table.name,
                    column.name,
                    col_type,
                )
