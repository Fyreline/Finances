"""One-off deletion of confirmed-non-rental documents — docs/phases/PHASE-13-
rental-history-and-safe-to-spend-fix.md item B.

Real, explicit user request: delete the documents that clearly aren't rental
paperwork (i.e. not from the letting agent). Phase 12 deliberately only
*reclassified* keyword-false-positive documents to `doc_type='other'` rather
than deleting them (a conservative default). The user has since asked outright
for deletion, which supersedes that default — but only for the unambiguous
noise bucket.

**`insurance` and `mortgage_interest_cert` documents are never touched here** —
a judgement call already made (docs/phases/PHASE-13 item B, not this module's
to relitigate): they are genuine property-related paperwork, not the
bank/broker/energy "statement" noise the user means, and directly feed
HANDOFF's still-open tax questions.

This is a real, irreversible local deletion (DB rows + on-disk folders). The
caller is expected to have backed up the DB and copied `tax-documents/` first
(the same discipline every prior data-touching phase used) — this module does
not gate on that itself, it just reports exactly what it removed so the action
is never silent.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import RentalLedgerEntry, TaxDocument
from .rent_statement_ingest import resolve_document_folder

# The unambiguous noise bucket (docs/phases/PHASE-13 item B): bank/broker/
# energy/game-storefront emails that Phase 12's keyword classifier swept in
# and were never anything rental-related. Every other doc_type — including
# `insurance` and `mortgage_interest_cert` — is deliberately excluded.
DELETABLE_DOC_TYPES = frozenset({"other"})


@dataclass
class CleanupResult:
    scanned: int = 0
    deleted: int = 0
    skipped_had_ledger_rows: int = 0  # a genuine data dependency — never silently broken
    folders_removed: int = 0
    folders_missing: int = 0  # DB row deleted; its folder was already gone — not an error
    removed_folders: list[str] = field(default_factory=list)  # relative paths, for the run log only


def delete_non_rental_documents(
    session: Session,
    *,
    doc_types: frozenset[str] = DELETABLE_DOC_TYPES,
    docs_root: Path | None = None,
) -> CleanupResult:
    """Delete every `TaxDocument` row (and its on-disk folder) whose
    ``doc_type`` is in ``doc_types`` (default: just ``'other'``). A document
    with any linked `RentalLedgerEntry` rows is skipped, not deleted — the
    noise bucket is never auto-ledgered by this pipeline (docs/phases/PHASE-12
    item 1d only auto-ledgers *confirmed* rent statements), so this should be
    rare in practice, but a document a human has since manually linked into
    the ledger must never be silently destroyed. Idempotent: a second run
    finds nothing left to delete."""
    result = CleanupResult()
    rows = session.scalars(select(TaxDocument).where(TaxDocument.doc_type.in_(doc_types))).all()
    result.scanned = len(rows)

    ledger_counts = {
        doc_id: count
        for doc_id, count in session.execute(
            select(RentalLedgerEntry.tax_document_id, func.count())
            .where(RentalLedgerEntry.tax_document_id.in_([d.id for d in rows]))
            .group_by(RentalLedgerEntry.tax_document_id)
        ).all()
    }

    for doc in rows:
        if ledger_counts.get(doc.id, 0) > 0:
            result.skipped_had_ledger_rows += 1
            continue

        folder = resolve_document_folder(doc, docs_root)
        if folder.is_dir():
            shutil.rmtree(folder)
            result.folders_removed += 1
            result.removed_folders.append(doc.file_path)
        else:
            result.folders_missing += 1

        session.delete(doc)
        result.deleted += 1

    session.commit()
    return result
