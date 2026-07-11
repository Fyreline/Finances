"""Confirmed-non-rental document deletion — app/rental_document_cleanup.py,
docs/phases/PHASE-13-rental-history-and-safe-to-spend-fix.md item B. Synthetic
docs only (docs/PRIVATE.md redaction scheme)."""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import RentalLedgerEntry, TaxDocument
from app.rental_document_cleanup import delete_non_rental_documents
from app.tax_years import seed_tax_years


def _doc(session, mid, doc_type, file_path, subject="Test doc", from_addr="noreply@example.com"):
    d = TaxDocument(
        tax_year="2025-26", source="gmail", gmail_message_id=mid, doc_type=doc_type,
        received_at="2025-10-20", from_addr=from_addr, subject=subject, file_path=file_path,
        amount_minor=None, amount_confidence="none", reviewed=0,
    )
    session.add(d)
    return d


def test_deletes_other_documents_and_their_folders(tmp_path):
    docs_root = tmp_path / "tax-documents"
    other_folder = docs_root / "2025-26" / "2025-10-20-other-bank-statement"
    other_folder.mkdir(parents=True)
    (other_folder / "message.json").write_text("{}")

    with SessionLocal() as session:
        seed_tax_years(session)
        _doc(session, "n1", "other", str(other_folder.relative_to(tmp_path)))
        session.commit()

        res = delete_non_rental_documents(session, docs_root=docs_root)
        assert res.scanned == 1
        assert res.deleted == 1
        assert res.folders_removed == 1
        assert res.skipped_had_ledger_rows == 0

        assert session.query(TaxDocument).filter_by(gmail_message_id="n1").first() is None
        assert not other_folder.exists()


def test_insurance_and_mortgage_interest_cert_are_never_deleted(tmp_path):
    docs_root = tmp_path / "tax-documents"
    ins_folder = docs_root / "2025-26" / "2025-10-20-insurance-renewal"
    ins_folder.mkdir(parents=True)
    mic_folder = docs_root / "2025-26" / "2025-10-20-mortgage_interest_cert-cert"
    mic_folder.mkdir(parents=True)
    other_folder = docs_root / "2025-26" / "2025-10-20-other-noise"
    other_folder.mkdir(parents=True)

    with SessionLocal() as session:
        seed_tax_years(session)
        _doc(session, "i1", "insurance", str(ins_folder.relative_to(tmp_path)))
        _doc(session, "m1", "mortgage_interest_cert", str(mic_folder.relative_to(tmp_path)))
        _doc(session, "o1", "other", str(other_folder.relative_to(tmp_path)))
        session.commit()

        res = delete_non_rental_documents(session, docs_root=docs_root)
        assert res.scanned == 1  # only 'other' was ever a candidate
        assert res.deleted == 1

        types = {d.gmail_message_id: d.doc_type for d in session.query(TaxDocument).all()}
        assert types == {"i1": "insurance", "m1": "mortgage_interest_cert"}
        assert ins_folder.exists() and mic_folder.exists()
        assert not other_folder.exists()


def test_document_with_linked_ledger_rows_is_skipped_not_deleted(tmp_path):
    docs_root = tmp_path / "tax-documents"
    folder = docs_root / "2025-26" / "2025-10-20-other-linked"
    folder.mkdir(parents=True)

    with SessionLocal() as session:
        seed_tax_years(session)
        doc = _doc(session, "o1", "other", str(folder.relative_to(tmp_path)))
        doc.reviewed = 1
        session.commit()
        session.refresh(doc)
        session.add(
            RentalLedgerEntry(
                tax_year="2025-26", local_date="2025-10-15", kind="income",
                amount_minor=50_000, source="manual", tax_document_id=doc.id,
            )
        )
        session.commit()

        res = delete_non_rental_documents(session, docs_root=docs_root)
        assert res.scanned == 1
        assert res.deleted == 0
        assert res.skipped_had_ledger_rows == 1

        assert session.query(TaxDocument).filter_by(gmail_message_id="o1").first() is not None
        assert folder.exists()  # untouched — the DB row was never deleted


def test_missing_folder_is_not_an_error(tmp_path):
    # A document row whose folder is already gone (e.g. manually cleaned up) —
    # the DB row must still be deleted, just counted as folders_missing.
    docs_root = tmp_path / "tax-documents"
    with SessionLocal() as session:
        seed_tax_years(session)
        _doc(session, "n1", "other", "tax-documents/2025-26/already-gone")
        session.commit()

        res = delete_non_rental_documents(session, docs_root=docs_root)
        assert res.deleted == 1
        assert res.folders_missing == 1
        assert res.folders_removed == 0


def test_idempotent_second_run_finds_nothing(tmp_path):
    docs_root = tmp_path / "tax-documents"
    folder = docs_root / "2025-26" / "2025-10-20-other-noise"
    folder.mkdir(parents=True)

    with SessionLocal() as session:
        seed_tax_years(session)
        _doc(session, "o1", "other", str(folder.relative_to(tmp_path)))
        session.commit()

        first = delete_non_rental_documents(session, docs_root=docs_root)
        assert first.deleted == 1

        second = delete_non_rental_documents(session, docs_root=docs_root)
        assert second.scanned == 0
        assert second.deleted == 0
