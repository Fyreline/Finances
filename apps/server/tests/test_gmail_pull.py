"""The rental-email pull pipeline — app/gmail_pull.py, docs/API.md §3c.

Runs against a fake Gmail service (no live Google). Proves: correctly-dated
tax-year folders across the 5/6 April boundary, an idempotent re-run that adds
nothing, ``reviewed=0`` on every pulled doc, conservative amount parsing, and
the ``not_configured`` no-op when no sender is configured yet
(docs/phases/PHASE-5 acceptance).
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from app.config import get_settings
from app.db import SessionLocal
from app.gmail_pull import (
    build_query,
    classify_doc_type,
    parse_amount_minor,
    pull_rental_emails,
)
from app.models import TaxDocument
from app.tax_years import seed_tax_years

from tests.test_gmail_client import FakeGmailService


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _epoch_ms(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1000))


def _message(msg_id: str, subject: str, from_addr: str, when: datetime, body: str, *, attachment_id: str | None = None) -> dict:
    parts = [{"mimeType": "text/plain", "body": {"data": _b64(body)}}]
    if attachment_id:
        parts.append(
            {"mimeType": "application/pdf", "filename": "statement.pdf", "body": {"attachmentId": attachment_id}}
        )
    return {
        "id": msg_id,
        "internalDate": _epoch_ms(when),
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_addr},
            ],
            "parts": parts,
        },
    }


def test_build_query_empty_without_senders():
    assert build_query(None, [], days=400) == ""
    q = build_query("letting-co", ["agent@example.com"], days=400)
    assert "from:(agent@example.com OR letting-co)" in q and "newer_than:400d" in q


def test_classify_and_parse_amount():
    assert classify_doc_type("noreply@lender.example", "Your annual mortgage interest certificate") == "mortgage_interest_cert"
    # rent_statement is now assigned ONLY to a confirmed letting-agent statement
    # (exact subject prefix, or the configured agent domain) — docs/phases/
    # PHASE-12 item 1a. A fuzzy "statement"/"rent" keyword no longer qualifies.
    assert classify_doc_type("agent@example.com", "Monthly Rental Statement for X - Y (Sep 2025)") == "rent_statement"
    assert classify_doc_type("noreply@agent.example.com", "Your account activity", agent_domain="agent.example.com") == "rent_statement"
    # These previously tripped the broad keyword rule into rent_statement; now honestly 'other'.
    assert classify_doc_type("noreply@bank.example", "Your latest current account statement") == "other"
    assert classify_doc_type("agent@example.com", "Monthly rent statement") == "other"
    assert classify_doc_type("hmrc@example.gov.uk", "Your Self Assessment tax return") == "other"
    assert parse_amount_minor("Rent received £850.00 this month") == (85_000, "parsed")
    # Two distinct amounts → left for a human, never guessed.
    assert parse_amount_minor("Rent £850.00 less fee £85.00") == (None, "none")


def test_pull_crosses_5_6_april_boundary_and_is_idempotent(tmp_path):
    settings = get_settings()
    docs_root = tmp_path / "tax-documents"

    # 5 Apr 2025 → tax year 2024-25 ; 6 Apr 2025 → tax year 2025-26.
    before = datetime(2025, 4, 5, 9, 0, tzinfo=timezone.utc)
    after = datetime(2025, 4, 6, 9, 0, tzinfo=timezone.utc)
    messages = [
        _message("m-apr5", "Rent statement", "agent@example.com", before, "Rent received £850.00", attachment_id="att5"),
        _message("m-apr6", "Rent statement", "agent@example.com", after, "Rent received £850.00", attachment_id="att6"),
    ]
    service = FakeGmailService(
        pages={None: {"messages": [{"id": m["id"]} for m in messages]}},
        by_id={m["id"]: m for m in messages},
        attachments={"att5": _b64("pdf-five"), "att6": _b64("pdf-six")},
    )

    with SessionLocal() as session:
        seed_tax_years(session)
        run = pull_rental_emails(
            session, settings, letting_agent="agent@example.com", service=service, docs_root=docs_root
        )
        assert run.status == "ok" and run.new_rows == 2

        docs = session.query(TaxDocument).order_by(TaxDocument.received_at).all()
        years = {d.received_at: d.tax_year for d in docs}
        assert years["2025-04-05"] == "2024-25"
        assert years["2025-04-06"] == "2025-26"
        # Every pulled doc is unreviewed and amount-parsed conservatively.
        assert all(d.reviewed == 0 for d in docs)
        assert all(d.amount_minor == 85_000 and d.amount_confidence == "parsed" for d in docs)

        # Dated folders exist on disk, one per tax year, with the attachment saved.
        assert (docs_root / "2024-25").is_dir()
        assert (docs_root / "2025-26").is_dir()
        saved = list(docs_root.glob("2025-26/*/statement.pdf"))
        assert saved and saved[0].read_bytes() == b"pdf-six"

        # Re-run: dedup on gmail_message_id → adds nothing.
        rerun = pull_rental_emails(
            session, settings, letting_agent="agent@example.com", service=service, docs_root=docs_root
        )
        assert rerun.status == "ok" and rerun.new_rows == 0
        assert rerun.detail is None
        assert session.query(TaxDocument).count() == 2


def test_pull_not_configured_without_sender(tmp_path):
    settings = get_settings()
    with SessionLocal() as session:
        seed_tax_years(session)
        run = pull_rental_emails(
            session, settings, letting_agent=None, service=FakeGmailService(pages={None: {"messages": []}}),
            docs_root=tmp_path,
        )
        assert run.status == "not_configured" and run.new_rows == 0
