"""The rental-email pull pipeline — docs/API.md §3c, docs/TAX.md §6.

Orchestration (I/O: the Gmail client, the filesystem, the DB) lives here so the
Gmail client stays a thin read-only wrapper and ``engines/`` stays pure. Both
``scripts/pull_rental_emails.py`` (the weekly LaunchAgent entrypoint) and the
test suite call :func:`pull_rental_emails` directly — neither re-implements the
classify/save/dedup logic.

Discipline mirrored from the Starling/T212 sync engines:
- **Idempotent** — dedup on ``tax_documents.gmail_message_id`` (a unique
  column), so a re-run adds nothing (docs/phases/PHASE-5-tax.md acceptance).
- **Never raises** — degrades to a ``not_configured`` sync row when Gmail
  isn't authorised or no query is configured yet, an ``error`` row on any
  Google/network failure; the caller always gets a :class:`SyncRun` back.
- **Never silently becomes tax data** — every pulled doc lands with
  ``reviewed=0`` and a conservative amount parse; a human confirms type +
  amount on the TaxPage before anything can flow into ``rental_ledger``
  (docs/API.md §3c, enforced by ``routers/tax.py``).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import PROJECT_ROOT, Settings
from .dates import tax_year_of, to_local_date
from .integrations.gmail import GmailClient, GmailUnavailable, NotConfigured
from .models import SyncRun, TaxDocument, TaxYear
from .tax_years import ensure_tax_year

logger = logging.getLogger(__name__)

TAX_DOCS_DIR = PROJECT_ROOT / "tax-documents"

# docs/API.md §3c subject keywords. Rental paperwork + — per HANDOFF Q2, the
# deadline-critical question — HMRC Self Assessment and accountant
# correspondence, so the pipeline can help resolve whether the right tax year's
# rental income was actually declared.
SUBJECT_KEYWORDS = (
    "rent",
    "statement",
    "mortgage interest",
    "landlord insurance",
    "self assessment",
    "tax return",
    "UTR",
    "HMRC",
)

_DB_TS_FMT = "%Y-%m-%d %H:%M:%S"
# A single unambiguous £ amount → confidence 'parsed'; anything else stays for a
# human (docs/API.md §3c "amount_confidence='parsed' only on a single
# unambiguous hit").
_AMOUNT_RE = re.compile(r"£\s?([\d,]+\.\d{2})")


def build_query(letting_agent: str | None, senders: list[str], *, days: int = 400) -> str:
    """The Gmail search query (docs/API.md §3c). Returns ``""`` when no
    sender-specific config exists yet (HANDOFF Q3 unanswered) — the caller
    treats an empty query as ``not_configured`` and no-ops, rather than
    scanning the whole mailbox on subject keywords alone."""
    from_terms = [s.strip() for s in senders if s.strip()]
    if letting_agent and letting_agent.strip():
        from_terms.append(letting_agent.strip())
    if not from_terms:
        return ""
    subject = " OR ".join(f'"{k}"' for k in SUBJECT_KEYWORDS)
    senders_expr = " OR ".join(from_terms)
    return f"(from:({senders_expr}) OR subject:({subject})) newer_than:{days}d"


def classify_doc_type(from_addr: str | None, subject: str | None) -> str:
    """Classify into the ``tax_documents.doc_type`` taxonomy (DATA_MODEL §6) by
    sender + subject keywords. Conservative — anything unrecognised (including
    HMRC/accountant correspondence, which has no dedicated type) is ``other``,
    for a human to confirm on the review queue."""
    haystack = f"{from_addr or ''} {subject or ''}".lower()

    def has(*words: str) -> bool:
        return any(w in haystack for w in words)

    if has("mortgage interest", "interest certificate", "interest statement"):
        return "mortgage_interest_cert"
    if has("ground rent", "factor", "service charge", "feu"):
        return "ground_rent"
    if has("insurance", "policy", "cover"):
        return "insurance"
    if has("repair", "boiler", "plumber", "electrician", "maintenance"):
        return "repair_invoice"
    if has("invoice", "fee", "commission"):
        return "agent_invoice"
    if has("rent", "statement", "tenancy"):
        return "rent_statement"
    return "other"  # HMRC SA correspondence, accountant emails, anything else


def parse_amount_minor(text: str) -> tuple[int | None, str]:
    """Conservative amount parse (docs/API.md §3c). Returns
    ``(amount_minor, confidence)`` — ``'parsed'`` only when exactly one
    distinct £ amount appears; multiple or none leaves it for a human
    (``'none'``), never a guess that could silently become tax data."""
    matches = {m.replace(",", "") for m in _AMOUNT_RE.findall(text)}
    if len(matches) != 1:
        return None, "none"
    pounds = float(next(iter(matches)))
    return round(pounds * 100), "parsed"


def _header(headers: list[dict], name: str) -> str | None:
    lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == lower:
            return h.get("value")
    return None


def _walk_parts(payload: dict) -> tuple[str, list[dict]]:
    """Depth-first walk of a Gmail message payload → (decoded text body,
    attachment part list). Attachments are parts with a filename + an
    ``attachmentId``."""
    text_chunks: list[str] = []
    attachments: list[dict] = []

    def visit(part: dict) -> None:
        body = part.get("body", {})
        filename = part.get("filename") or ""
        mime = part.get("mimeType", "")
        if filename and body.get("attachmentId"):
            attachments.append(
                {"filename": filename, "mime_type": mime, "attachment_id": body["attachmentId"]}
            )
        elif mime.startswith("text/") and body.get("data"):
            try:
                text_chunks.append(base64.urlsafe_b64decode(body["data"]).decode("utf-8", "replace"))
            except (ValueError, TypeError):
                pass
        for child in part.get("parts", []) or []:
            visit(child)

    visit(payload)
    return "\n".join(text_chunks), attachments


def _received_local_date(message: dict) -> str:
    """The message's Europe/London calendar date, from ``internalDate`` (epoch
    ms, authoritative) — used for both the tax-year folder and the DB row so a
    5 April vs 6 April email lands in the correct SA year (docs/dates.py)."""
    internal = message.get("internalDate")
    if internal:
        dt = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)
        return to_local_date(dt)
    headers = message.get("payload", {}).get("headers", [])
    date_hdr = _header(headers, "Date")
    if date_hdr:
        try:
            from email.utils import parsedate_to_datetime

            return to_local_date(parsedate_to_datetime(date_hdr))
        except (TypeError, ValueError):
            pass
    return to_local_date(datetime.now(timezone.utc))


def _slug(text: str, *, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:limit] or "untitled").strip("-")


@dataclass
class GmailPullResult:
    status: str  # 'ok' | 'not_configured' | 'error'
    new_documents: int
    skipped_existing: int
    detail: str | None = None


def pull_rental_emails(
    session: Session,
    settings: Settings,
    *,
    letting_agent: str | None = None,
    service: object | None = None,
    docs_root: Path | None = None,
    now: datetime | None = None,
) -> SyncRun:
    """Pull rental paperwork into ``tax-documents/<tax-year>/`` + ``tax_documents``
    rows. Writes one ``sync_runs`` row (provider ``gmail``) for observability,
    exactly like the Starling/T212 syncs, and never raises."""
    now = now or datetime.now(timezone.utc)
    started_at = now.strftime(_DB_TS_FMT)
    docs_root = docs_root or TAX_DOCS_DIR

    senders = [s for s in (settings.gmail_senders or "").split(",") if s.strip()]
    query = build_query(letting_agent, senders, days=settings.gmail_search_days)

    def _terminal_run(status: str, detail: str | None, new_docs: int = 0) -> SyncRun:
        run = SyncRun(
            provider="gmail",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).strftime(_DB_TS_FMT),
            status=status,
            new_rows=new_docs,
            detail=detail,
        )
        session.add(run)
        session.commit()
        return run

    if not query:
        return _terminal_run(
            "not_configured",
            "No letting-agent/sender configured yet (HANDOFF Q3) — nothing to search",
        )

    # Build a real client unless a fake service is injected (tests / no-google).
    try:
        client = GmailClient(
            settings.gmail_credentials_path,
            settings.gmail_token_path,
            service=service,  # type: ignore[arg-type]
        )
    except NotConfigured as exc:
        return _terminal_run("not_configured", str(exc))
    except GmailUnavailable as exc:
        return _terminal_run("error", str(exc)[:500])

    new_docs = 0
    skipped = 0
    try:
        refs = client.search(query)
        for ref in refs:
            existing = session.scalar(
                select(TaxDocument).where(TaxDocument.gmail_message_id == ref.message_id)
            )
            if existing is not None:
                skipped += 1
                continue

            message = client.fetch_message(ref.message_id)
            payload = message.get("payload", {})
            headers = payload.get("headers", [])
            subject = _header(headers, "Subject")
            from_addr = _header(headers, "From")
            local_date = _received_local_date(message)
            tax_year = tax_year_of(local_date)
            ensure_tax_year(session, tax_year)

            doc_type = classify_doc_type(from_addr, subject)
            body_text, attachments = _walk_parts(payload)
            amount_minor, confidence = parse_amount_minor(f"{subject or ''}\n{body_text}")

            folder = docs_root / tax_year / f"{local_date}-{doc_type}-{_slug(subject or ref.message_id)}"
            folder.mkdir(parents=True, exist_ok=True)
            # The raw artifact for the accountant handover — the full message
            # payload as received (docs/TAX.md §6). Read-only: we save what
            # Gmail returned, we never write anything back to the mailbox.
            (folder / "message.json").write_text(json.dumps(message, indent=2))
            for att in attachments:
                try:
                    data = client.fetch_attachment(ref.message_id, att["attachment_id"])
                    (folder / _safe_filename(att["filename"])).write_bytes(data)
                except GmailUnavailable as exc:  # one bad attachment shouldn't sink the pull
                    logger.warning("gmail_pull: attachment fetch failed: %s", exc)

            session.add(
                TaxDocument(
                    tax_year=tax_year,
                    source="gmail",
                    gmail_message_id=ref.message_id,
                    doc_type=doc_type,
                    received_at=local_date,
                    from_addr=from_addr,
                    subject=subject,
                    file_path=str(folder.relative_to(docs_root.parent))
                    if docs_root.parent in folder.parents
                    else str(folder),
                    amount_minor=amount_minor,
                    amount_confidence=confidence,
                    reviewed=0,
                )
            )
            session.commit()
            new_docs += 1

        return _terminal_run("ok", None, new_docs)
    except GmailUnavailable as exc:
        logger.warning("gmail_pull: %s", exc)
        return _terminal_run("error", str(exc)[:500], new_docs)


def _safe_filename(name: str) -> str:
    """Strip path separators from an attachment filename so a hostile/odd name
    can't escape the document folder."""
    return Path(name).name or "attachment"
