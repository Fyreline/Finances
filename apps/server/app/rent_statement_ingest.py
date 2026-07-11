"""Confirmed-rent-statement detection + PDF-to-ledger automation (docs/phases/
PHASE-12-rental-automation.md items 1a/1b/1d).

The I/O half of the rent-statement pipeline: it decides whether a document is a
*confirmed* letting-agent monthly statement, opens the statement PDF (lazy PDF
library, degrades gracefully if absent), runs the pure
`engines/rent_statement_parser`, and — only for a confident, itemised parse —
creates the matching `rental_ledger` rows and marks the document reviewed. Both
`gmail_pull.pull_rental_emails` (fresh pulls) and
`scripts/backfill_rental_automation.py` (the one-off backfill of the already-
pulled statements) call `auto_ledger_from_document`; neither re-implements it.

The deliberate, narrow relaxation of "unreviewed docs can't become tax data"
(docs/phases/PHASE-12 "Hard constraints"): this path sets `reviewed=1` **itself,
only at the moment it successfully creates the matching ledger rows**, and only
for a document that passed the strict `is_confirmed_rent_statement` sender/
subject gate AND parsed confidently against the learned layout. It never removes
or bypasses `routers/tax.py`'s `document_unreviewed` gate for anything else — a
non-confirmed document, or a confirmed one that fails to parse, keeps today's
behaviour exactly (`reviewed=0`, sits in the human review queue, no ledger rows).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import PROJECT_ROOT
from .dates import tax_year_of
from .engines.rent_statement_parser import ParsedStatement, parse_statement_text
from .models import RentalLedgerEntry, TaxDocument
from .tax_years import ensure_tax_year

logger = logging.getLogger(__name__)

# The letting agent's statements carry this exact subject prefix, confirmed
# directly against the real messages (docs/phases/PHASE-12 item 1a). It names no
# person and no figure, so it is safe to commit as a constant; the identifying
# *sender domain* is deliberately NOT hardcoded here (redaction + "no magic
# string sprinkled through the codebase") — it comes from configuration
# (`Settings.rent_statement_sender_domain`, empty by default) and is passed in.
CONFIRMED_SUBJECT_PREFIX = "Monthly Rental Statement "


def is_confirmed_rent_statement(
    from_addr: str | None, subject: str | None, *, agent_domain: str | None = None
) -> bool:
    """The strict gate for both re-classifying the review queue and triggering
    the auto-ledger pipeline (docs/phases/PHASE-12 item 1a). True only when the
    subject starts with the exact statement prefix, OR the message is from the
    configured letting-agent sender domain — never a fuzzy keyword match (which
    is what wrongly swept HSBC/energy/broker "statement" emails into the
    rent-statement queue). The domain arm is a no-op until the domain is
    configured, so the subject-prefix arm alone is what a fresh checkout relies
    on."""
    subj = (subject or "").strip()
    if subj.startswith(CONFIRMED_SUBJECT_PREFIX):
        return True
    domain = (agent_domain or "").strip().lower()
    if domain and domain in (from_addr or "").lower():
        return True
    return False


def find_statement_pdf(folder: Path) -> Path | None:
    """Pick the monthly-statement PDF out of a document folder that may also
    hold inline signature images (`image001.jpg` …) and standalone contractor
    invoices (docs/phases/PHASE-12 item 1a: "filter to .pdf and, if a folder has
    multiple PDFs, prefer the one whose filename contains 'Statement'"). Returns
    ``None`` when nothing looks like the statement (ambiguous → leave for a
    human), never a guess."""
    if not folder.is_dir():
        return None
    pdfs = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        return None
    monthly = [p for p in pdfs if "monthly statement" in p.name.lower()]
    if monthly:
        return monthly[0]
    statement = [p for p in pdfs if "statement" in p.name.lower()]
    if statement:
        return statement[0]
    return pdfs[0] if len(pdfs) == 1 else None


def extract_pdf_text(path: Path) -> str | None:
    """All-pages text via ``pdfplumber``, imported lazily (mirrors
    `integrations/gmail.py`'s lazy Google import) so the test suite and any
    runtime without the library degrade gracefully — a missing library or an
    unreadable PDF returns ``None``, which the caller treats as "couldn't parse,
    leave for a human", never a crash (docs/phases/PHASE-12 item 1b)."""
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        logger.warning("rent_statement_ingest: pdfplumber not installed — statement left for manual review")
        return None
    try:
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:  # a malformed PDF must not sink the pull/backfill
        logger.warning("rent_statement_ingest: could not read %s: %s", path.name, exc)
        return None


def resolve_document_folder(doc: TaxDocument, docs_root: Path | None = None) -> Path:
    """The on-disk folder for a document. ``TaxDocument.file_path`` is stored
    relative to the project root (e.g. ``tax-documents/2025-26/...``); resolve it
    against that root unless it is already absolute."""
    p = Path(doc.file_path)
    if p.is_absolute():
        return p
    base = docs_root.parent if docs_root is not None else PROJECT_ROOT
    return base / p


@dataclass
class AutoLedgerResult:
    document_id: int | None
    outcome: str  # see the constants below
    created_rows: int = 0
    period_label: str | None = None
    detail: str | None = None


# outcome values
LEDGERED = "ledgered"  # confident parse → income + expense rows created, reviewed=1
ALREADY_LEDGERED = "already_ledgered"  # rows already linked to this doc — idempotent no-op
TOPPED_UP = "topped_up"  # already-ledgered doc gained newly-parsed property-cost rows
NOT_CONFIRMED = "not_confirmed"  # failed is_confirmed_rent_statement — nothing done
NO_PDF = "no_pdf"  # no statement PDF found in the folder
NO_TEXT = "no_text"  # PDF unreadable / library missing
UNCONFIDENT = "unconfident"  # parsed but not confident — left for human review


def auto_ledger_from_document(
    session: Session,
    doc: TaxDocument,
    *,
    folder: Path | None = None,
    docs_root: Path | None = None,
    agent_domain: str | None = None,
) -> AutoLedgerResult:
    """Turn one confirmed rent-statement document into ledger rows, idempotently.

    Returns without side effects (beyond an at-most-once ``commit``) in every
    non-``LEDGERED`` case. Idempotency keys off ``tax_document_id``: a document
    already linked to any ledger row is never re-ledgered, so re-running the
    backfill or a future pull can only ever add rows for documents that have
    none (docs/phases/PHASE-12 item 1d)."""
    if not is_confirmed_rent_statement(doc.from_addr, doc.subject, agent_domain=agent_domain):
        return AutoLedgerResult(doc.id, NOT_CONFIRMED)

    existing = session.scalar(
        select(func.count()).select_from(RentalLedgerEntry).where(RentalLedgerEntry.tax_document_id == doc.id)
    )
    if existing:
        # Already ledgered by Phase 12 (income + agent_fees) — but it may predate
        # the Property Costs Summary parser, so additively add any missing
        # repairs rows without re-creating the income/agent_fees pair (docs/
        # phases/PHASE-13 item C). Idempotent; safe to re-run.
        return _topup_property_costs(session, doc, folder=folder, docs_root=docs_root)

    parsed, failure = _parse_document(doc, folder=folder, docs_root=docs_root)
    if failure is not None:
        return AutoLedgerResult(doc.id, failure)
    assert parsed is not None  # guaranteed by `_parse_document`'s contract when failure is None
    if not parsed.confident:
        # Partial parse: surface the gross rent it *did* find as a review hint
        # (populate what it found, leave the rest for a human — docs/phases/
        # PHASE-12 item 1c) without marking reviewed or creating any ledger row.
        if parsed.gross_rent_minor is not None and doc.amount_minor is None:
            doc.amount_minor = parsed.gross_rent_minor
            doc.amount_confidence = "guessed"
            session.commit()
        return AutoLedgerResult(
            doc.id, UNCONFIDENT, period_label=parsed.period_label, detail="; ".join(parsed.warnings) or None
        )

    created = _write_ledger_rows(session, doc, parsed)
    # The narrow, deliberate reviewed=1 relaxation — set only now, having created
    # the matching itemised rows (docs/phases/PHASE-12 "Hard constraints").
    doc.reviewed = 1
    doc.amount_minor = parsed.gross_rent_minor
    doc.amount_confidence = "parsed"
    session.commit()
    return AutoLedgerResult(doc.id, LEDGERED, created_rows=created, period_label=parsed.period_label)


def _parse_document(
    doc: TaxDocument, *, folder: Path | None = None, docs_root: Path | None = None
) -> tuple[ParsedStatement | None, str | None]:
    """Resolve the document's folder, find its statement PDF, extract text, and
    parse it. Returns ``(parsed, None)`` on success or ``(None, outcome)`` for
    the two ways this can fail before parsing even starts (docs/phases/
    PHASE-12 item 1b) — shared by the first-time ledger path and the item-C
    top-up path so neither re-implements PDF discovery."""
    resolved_folder = folder or resolve_document_folder(doc, docs_root)
    pdf = find_statement_pdf(resolved_folder)
    if pdf is None:
        return None, NO_PDF
    text = extract_pdf_text(pdf)
    if text is None:
        return None, NO_TEXT
    return parse_statement_text(text), None


def _existing_ledger_expense_types(session: Session, doc: TaxDocument) -> set[str | None]:
    return set(
        session.scalars(
            select(RentalLedgerEntry.expense_type).where(
                RentalLedgerEntry.tax_document_id == doc.id, RentalLedgerEntry.kind == "expense"
            )
        ).all()
    )


def _topup_property_costs(
    session: Session, doc: TaxDocument, *, folder: Path | None = None, docs_root: Path | None = None
) -> AutoLedgerResult:
    """For a document already ledgered (Phase 12's income + agent_fees pair),
    additively create a ``repairs`` row for the Property Costs Summary section's
    itemised deductions (docs/phases/PHASE-13 item C) if the parser now finds
    ones that weren't captured the first time round — without touching or
    duplicating the existing income/agent_fees rows. Idempotent per document: a
    ``repairs`` row already present means this document has already been topped
    up (or was ledgered fresh with costs included), so a re-run is a no-op."""
    existing_count = session.scalar(
        select(func.count()).select_from(RentalLedgerEntry).where(RentalLedgerEntry.tax_document_id == doc.id)
    ) or 0
    if "repairs" in _existing_ledger_expense_types(session, doc):
        return AutoLedgerResult(doc.id, ALREADY_LEDGERED, detail=f"{existing_count} row(s) already linked")

    parsed, failure = _parse_document(doc, folder=folder, docs_root=docs_root)
    if failure is not None or parsed is None:
        return AutoLedgerResult(doc.id, ALREADY_LEDGERED, detail=f"{existing_count} row(s) already linked")

    costs = parsed.repairs_rows()
    if not costs:
        return AutoLedgerResult(doc.id, ALREADY_LEDGERED, detail=f"{existing_count} row(s) already linked")

    # Anchor the top-up row to this document's existing income-row date so it
    # lands in the same tax year the doc was originally ledgered under, rather
    # than re-deriving from a fresh (possibly differently-formatted) re-parse.
    anchor_date = session.scalar(
        select(RentalLedgerEntry.local_date)
        .where(RentalLedgerEntry.tax_document_id == doc.id, RentalLedgerEntry.kind == "income")
        .limit(1)
    )
    if anchor_date is None:
        assert parsed.period_year is not None and parsed.period_month is not None
        anchor_date = f"{parsed.period_year:04d}-{parsed.period_month:02d}-15"
    tax_year = tax_year_of(anchor_date)
    ensure_tax_year(session, tax_year)
    label = parsed.period_label or anchor_date

    total = sum(c.amount_minor for c in costs)
    descriptions = "; ".join(c.description for c in costs)
    session.add(
        RentalLedgerEntry(
            tax_year=tax_year,
            local_date=anchor_date,
            kind="expense",
            expense_type="repairs",
            amount_minor=total,
            source="document",
            tax_document_id=doc.id,
            notes=f"Auto-parsed property costs (top-up) — {label} ({descriptions})",
        )
    )
    session.commit()
    return AutoLedgerResult(doc.id, TOPPED_UP, created_rows=1, period_label=parsed.period_label)


def _write_ledger_rows(session: Session, doc: TaxDocument, parsed: ParsedStatement) -> int:
    """Create one income row (rent) + one agent_fees expense row (+ one
    combined ``repairs`` row for the Property Costs Summary section's itemised
    lines, if any — docs/phases/PHASE-13 item C, falling back to the legacy
    single landlord-direct line for a statement with no costs section) for a
    confidently-parsed statement. Amounts are positive pence; ``kind``/
    ``expense_type`` carry the sign semantics (DATA_MODEL §6). The ledger date
    is the statement's *covered period* (mid-month), not the email's received
    date, so amounts land in the right SA year even when the two differ by a
    few days around month-end (docs/phases/PHASE-12 item 1c)."""
    assert parsed.period_year is not None and parsed.period_month is not None
    local_date = f"{parsed.period_year:04d}-{parsed.period_month:02d}-15"
    tax_year = tax_year_of(local_date)
    ensure_tax_year(session, tax_year)
    label = parsed.period_label or local_date

    rows: list[RentalLedgerEntry] = [
        RentalLedgerEntry(
            tax_year=tax_year,
            local_date=local_date,
            kind="income",
            expense_type=None,
            amount_minor=parsed.gross_rent_minor,
            source="document",
            tax_document_id=doc.id,
            notes=f"Auto-parsed rent received — {label}",
        ),
        RentalLedgerEntry(
            tax_year=tax_year,
            local_date=local_date,
            kind="expense",
            expense_type="agent_fees",
            amount_minor=parsed.agent_fee_minor,
            source="document",
            tax_document_id=doc.id,
            notes=f"Auto-parsed agent commission + VAT — {label}",
        ),
    ]
    costs = parsed.repairs_rows()  # itemised Property Costs Summary lines, or the
    #                                legacy single landlord-direct line as fallback
    if costs:
        total = sum(c.amount_minor for c in costs)
        descriptions = "; ".join(c.description for c in costs)
        rows.append(
            RentalLedgerEntry(
                tax_year=tax_year,
                local_date=local_date,
                kind="expense",
                expense_type="repairs",
                amount_minor=total,
                source="document",
                tax_document_id=doc.id,
                notes=f"Auto-parsed property costs — {label} ({descriptions})",
            )
        )
    session.add_all(rows)
    return len(rows)
