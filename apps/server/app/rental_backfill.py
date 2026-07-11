"""One-off data fixes for the rental-statement automation (docs/phases/
PHASE-12-rental-automation.md items 1a + 1d) — same category of scripted,
report-counts-not-values migration as Phase 10's `tax_config` field-setting.

Two independent, idempotent operations, each importable and unit-tested, run
together by `scripts/backfill_rental_automation.py`:

- `reclassify_misfiled_rent_statements` — the old broad keyword classifier swept
  unrelated "statement"/"rent" emails (bank statements, energy statements,
  broker contract notes) into `doc_type='rent_statement'`. Any such row that
  fails the strict `is_confirmed_rent_statement` gate is a real misclassification
  and is relabelled `'other'` (the honest fall-through label) — never deleted,
  so a human can still find it. Documents of *other* valid types
  (mortgage-interest cert, insurance, …) are untouched.
- `backfill_rental_ledger` — for every already-pulled confirmed statement with
  no ledger rows yet, parse its PDF and create the income + expense rows, fixing
  the `gross_rents_minor: 0` tax estimate. Idempotent via `auto_ledger_from_document`
  — including its docs/phases/PHASE-13 item C top-up path, which additively adds
  a `repairs` row (from the Property Costs Summary section) to a document that
  Phase 12 already ledgered without one, without touching or duplicating its
  existing income/agent_fees rows.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TaxDocument
from .rent_statement_ingest import (
    ALREADY_LEDGERED,
    LEDGERED,
    TOPPED_UP,
    auto_ledger_from_document,
    is_confirmed_rent_statement,
)


def reclassify_misfiled_rent_statements(session: Session, *, agent_domain: str | None = None) -> dict:
    """Relabel `doc_type='rent_statement'` documents that are not confirmed
    letting-agent statements to `'other'`. Returns
    ``{scanned, reclassified, kept}`` — counts only, no subjects/senders
    (docs/PRIVATE.md redaction scheme)."""
    rows = session.scalars(select(TaxDocument).where(TaxDocument.doc_type == "rent_statement")).all()
    reclassified = 0
    for d in rows:
        if not is_confirmed_rent_statement(d.from_addr, d.subject, agent_domain=agent_domain):
            d.doc_type = "other"
            reclassified += 1
    session.commit()
    return {"scanned": len(rows), "reclassified": reclassified, "kept": len(rows) - reclassified}


def backfill_rental_ledger(session: Session, *, agent_domain: str | None = None, docs_root: Path | None = None) -> dict:
    """Auto-create ledger rows for every confirmed rent statement not already
    ledgered. Idempotent (safe to re-run). Returns a counts dict keyed by
    outcome plus the total ledger rows created — no figures."""
    docs = session.scalars(select(TaxDocument)).all()
    confirmed = [d for d in docs if is_confirmed_rent_statement(d.from_addr, d.subject, agent_domain=agent_domain)]
    outcomes: Counter[str] = Counter()
    created_rows = 0
    for d in confirmed:
        res = auto_ledger_from_document(session, d, docs_root=docs_root, agent_domain=agent_domain)
        outcomes[res.outcome] += 1
        created_rows += res.created_rows
    return {
        "confirmed_statements": len(confirmed),
        "ledgered_now": outcomes.get(LEDGERED, 0),
        "already_ledgered": outcomes.get(ALREADY_LEDGERED, 0),
        # docs/phases/PHASE-13 item C: documents that already had income/agent_fees
        # rows from Phase 12 and just gained a newly-parsed `repairs` row.
        "topped_up": outcomes.get(TOPPED_UP, 0),
        "ledger_rows_created": created_rows,
        "outcomes": dict(outcomes),
    }
