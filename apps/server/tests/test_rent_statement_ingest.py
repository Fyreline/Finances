"""Confirmed-statement detection + PDF-to-ledger automation —
app/rent_statement_ingest.py, docs/phases/PHASE-12-rental-automation.md
items 1a/1b/1d.

The PDF library is never exercised here — `extract_pdf_text` is monkeypatched to
return SYNTHETIC statement text (mirrors gmail.py's fake-service pattern, so CI
needs no pdfplumber installed and no real statement). All figures are
placeholders (docs/PRIVATE.md redaction scheme).
"""
from __future__ import annotations

from sqlalchemy import select

import app.rent_statement_ingest as ingest
from app.db import SessionLocal
from app.models import RentalLedgerEntry, TaxDocument
from app.rent_statement_ingest import (
    ALREADY_LEDGERED,
    LEDGERED,
    NOT_CONFIRMED,
    UNCONFIDENT,
    auto_ledger_from_document,
    find_statement_pdf,
    is_confirmed_rent_statement,
)
from app.tax_years import seed_tax_years

_SYNTH_STATEMENT = """\
Monthly Rental Statement September 2025
Total Rent: £1,000.00
Commission: 9.00 % £90.00 Placeholder Tenant £2,400.00
VAT: 20.00 % £18.00
Net Rent sent to you: £842.00
Imported: Repairs & Maintenance (Landlord Direct) -£50.00
"""


def test_is_confirmed_rent_statement_subject_prefix_and_domain():
    assert is_confirmed_rent_statement("anyone@x.com", "Monthly Rental Statement for A - B (Sep 2025)") is True
    assert is_confirmed_rent_statement("agent@agent.example.com", "Your account update", agent_domain="agent.example.com") is True
    # No prefix, no configured domain → not confirmed (this is what stops the noise).
    assert is_confirmed_rent_statement("noreply@bank.example", "Your latest account statement") is False
    assert is_confirmed_rent_statement("agent@agent.example.com", "Your update", agent_domain=None) is False


def test_find_statement_pdf_prefers_monthly_statement(tmp_path):
    (tmp_path / "image001.jpg").write_bytes(b"img")
    (tmp_path / "SI 12345-Some Contractor.pdf").write_bytes(b"pdf")
    target = tmp_path / "P00000 - (REF) 202509 Monthly Statement.pdf"
    target.write_bytes(b"pdf")
    assert find_statement_pdf(tmp_path) == target


def test_find_statement_pdf_ambiguous_returns_none(tmp_path):
    (tmp_path / "a-invoice.pdf").write_bytes(b"pdf")
    (tmp_path / "b-invoice.pdf").write_bytes(b"pdf")
    assert find_statement_pdf(tmp_path) is None  # no "statement" pdf, >1 candidate → leave for human


def _seed_confirmed_doc(session, tmp_path) -> TaxDocument:
    seed_tax_years(session)
    (tmp_path / "P00000 202509 Monthly Statement.pdf").write_bytes(b"pdf")
    doc = TaxDocument(
        tax_year="2025-26", source="gmail", gmail_message_id="msg-1", doc_type="rent_statement",
        received_at="2025-09-20", from_addr="agent@agent.example.com",
        subject="Monthly Rental Statement for REF - Addr (September 2025)",
        file_path=str(tmp_path), amount_minor=None, amount_confidence="none", reviewed=0,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_confident_parse_creates_ledger_rows_marks_reviewed_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "extract_pdf_text", lambda path: _SYNTH_STATEMENT)
    with SessionLocal() as session:
        doc = _seed_confirmed_doc(session, tmp_path)
        res = auto_ledger_from_document(session, doc, folder=tmp_path)
        assert res.outcome == LEDGERED
        assert res.created_rows == 3  # income + agent_fees + repairs

        rows = session.scalars(
            select(RentalLedgerEntry).where(RentalLedgerEntry.tax_document_id == doc.id)
        ).all()
        by_kind = {(r.kind, r.expense_type): r.amount_minor for r in rows}
        assert by_kind[("income", None)] == 100_000
        assert by_kind[("expense", "agent_fees")] == 10_800  # commission + VAT
        assert by_kind[("expense", "repairs")] == 5_000
        # ledger date is the statement's covered period, mid-month, right SA year
        assert all(r.local_date == "2025-09-15" and r.tax_year == "2025-26" for r in rows)
        assert all(r.source == "document" for r in rows)

        session.refresh(doc)
        assert doc.reviewed == 1
        assert doc.amount_minor == 100_000 and doc.amount_confidence == "parsed"

        # Idempotent: a re-run creates nothing more.
        again = auto_ledger_from_document(session, doc, folder=tmp_path)
        assert again.outcome == ALREADY_LEDGERED and again.created_rows == 0
        assert session.query(RentalLedgerEntry).filter_by(tax_document_id=doc.id).count() == 3


def test_unconfident_parse_leaves_doc_for_review_no_ledger(tmp_path, monkeypatch):
    # Commission line absent → not confident. Sets a review hint amount, but
    # never reviewed=1 and never a ledger row (docs/phases/PHASE-12 item 1d).
    partial = "\n".join(l for l in _SYNTH_STATEMENT.splitlines() if not l.startswith("Commission"))
    monkeypatch.setattr(ingest, "extract_pdf_text", lambda path: partial)
    with SessionLocal() as session:
        doc = _seed_confirmed_doc(session, tmp_path)
        res = auto_ledger_from_document(session, doc, folder=tmp_path)
        assert res.outcome == UNCONFIDENT
        assert session.query(RentalLedgerEntry).filter_by(tax_document_id=doc.id).count() == 0
        session.refresh(doc)
        assert doc.reviewed == 0
        assert doc.amount_minor == 100_000 and doc.amount_confidence == "guessed"  # hint only


def test_non_confirmed_document_is_never_auto_ledgered(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "extract_pdf_text", lambda path: _SYNTH_STATEMENT)
    with SessionLocal() as session:
        seed_tax_years(session)
        doc = TaxDocument(
            tax_year="2025-26", source="gmail", gmail_message_id="msg-x", doc_type="other",
            received_at="2025-09-20", from_addr="noreply@bank.example",
            subject="Your latest account statement", file_path=str(tmp_path),
            amount_minor=None, amount_confidence="none", reviewed=0,
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        res = auto_ledger_from_document(session, doc, folder=tmp_path)
        assert res.outcome == NOT_CONFIRMED
        session.refresh(doc)
        assert doc.reviewed == 0
        assert session.query(RentalLedgerEntry).count() == 0
