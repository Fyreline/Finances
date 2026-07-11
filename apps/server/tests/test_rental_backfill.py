"""One-off reclassify + ledger backfill — app/rental_backfill.py, docs/phases/
PHASE-12-rental-automation.md items 1a + 1d. Synthetic docs only (redaction)."""
from __future__ import annotations

import app.rent_statement_ingest as ingest
from app.db import SessionLocal
from app.models import RentalLedgerEntry, TaxDocument
from app.rental_backfill import backfill_rental_ledger, reclassify_misfiled_rent_statements
from app.tax_years import seed_tax_years

_SYNTH_STATEMENT = """\
Monthly Rental Statement October 2025
Total Rent: £1,000.00
Commission: 9.00 % £90.00
VAT: 20.00 % £18.00
Net Rent sent to you: £892.00
"""


def _doc(session, mid, doc_type, subject, from_addr, file_path):
    d = TaxDocument(
        tax_year="2025-26", source="gmail", gmail_message_id=mid, doc_type=doc_type,
        received_at="2025-10-20", from_addr=from_addr, subject=subject, file_path=file_path,
        amount_minor=None, amount_confidence="none", reviewed=0,
    )
    session.add(d)
    return d


def test_reclassify_moves_false_positives_only(tmp_path):
    with SessionLocal() as session:
        seed_tax_years(session)
        _doc(session, "s1", "rent_statement", "Monthly Rental Statement for A - B (Oct 2025)", "agent@x.com", str(tmp_path))
        _doc(session, "s2", "rent_statement", "Your latest current account statement", "noreply@bank.example", str(tmp_path))
        _doc(session, "s3", "rent_statement", "Your energy statement", "noreply@octopus.energy", str(tmp_path))
        # A non-rent-statement type must be left completely alone.
        _doc(session, "i1", "insurance", "Landlord insurance renewal", "noreply@insurer.example", str(tmp_path))
        session.commit()

        res = reclassify_misfiled_rent_statements(session)
        assert res == {"scanned": 3, "reclassified": 2, "kept": 1}

        types = {d.gmail_message_id: d.doc_type for d in session.query(TaxDocument).all()}
        assert types["s1"] == "rent_statement"  # the real statement stays
        assert types["s2"] == "other" and types["s3"] == "other"
        assert types["i1"] == "insurance"  # untouched


def test_backfill_ledgers_confirmed_statements_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "extract_pdf_text", lambda path: _SYNTH_STATEMENT)
    folder = tmp_path / "stmt"
    folder.mkdir()
    (folder / "P0 202510 Monthly Statement.pdf").write_bytes(b"pdf")
    with SessionLocal() as session:
        seed_tax_years(session)
        _doc(session, "s1", "rent_statement", "Monthly Rental Statement for A - B (Oct 2025)", "agent@x.com", str(folder))
        _doc(session, "n1", "other", "Your latest account statement", "noreply@bank.example", str(tmp_path))
        session.commit()

        res = backfill_rental_ledger(session)
        assert res["confirmed_statements"] == 1
        assert res["ledgered_now"] == 1
        assert res["ledger_rows_created"] == 2  # income + agent_fees (no repairs this month)

        # gross rents now non-zero for the year — the whole point (fixes £0 estimate)
        income = session.query(RentalLedgerEntry).filter_by(kind="income").all()
        assert sum(r.amount_minor for r in income) == 100_000

        # Re-run is a no-op.
        res2 = backfill_rental_ledger(session)
        assert res2["ledgered_now"] == 0 and res2["already_ledgered"] == 1
        assert res2["ledger_rows_created"] == 0
        assert session.query(RentalLedgerEntry).count() == 2
