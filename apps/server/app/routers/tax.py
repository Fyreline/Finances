"""Tax surface — docs/API.md §5 "Tax", semantics governed by docs/TAX.md.

Endpoints: ``tax_config`` CRUD (the HANDOFF open-question inputs), the year
summary + estimate (``missing_inputs``/``disclaimer`` contract), the
SA105-shaped ``rental_ledger`` (+ CSV export for the accountant handover), the
document review queue, and the ``is_rental`` one-tap ledger candidates.

Two invariants enforced here:
- **The estimate refuses to guess** — it is ``null`` + ``missing_inputs`` while
  any required ``tax_config`` field is unset (docs/TAX.md §0), and the
  ``disclaimer`` string is on every response.
- **Unreviewed docs can't become tax data** — a ledger row may only link a
  ``tax_document_id`` whose row has ``reviewed=1`` (docs/API.md §3c,
  docs/phases/PHASE-5-tax.md acceptance).
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..dates import now_london, tax_year_bounds, tax_year_of
from ..db import get_session
from ..engines.tax import (
    ALLOWABLE_EXPENSE_TYPES,
    DISCLAIMER,
    EstimateInputs,
    estimate_tax,
    income_tax_minor,
    loss_brought_forward_minor,
    missing_inputs,
)
from ..engines.tax_rates import rates_for_year
from ..errors import KakeiboHTTPException
from ..models import Account, RentalLedgerEntry, TaxConfig, TaxDocument, Transaction
from ..tax_years import ensure_tax_year

router = APIRouter(tags=["tax"])

_EXPENSE_TYPES = {
    "agent_fees",
    "insurance",
    "repairs",
    "ground_rent_service",
    "other_allowable",
    "mortgage_interest",
    "capital_improvement",
}
_DOC_TYPES = {
    "rent_statement",
    "agent_invoice",
    "mortgage_interest_cert",
    "insurance",
    "repair_invoice",
    "ground_rent",
    "other",
}


# --------------------------------------------------------------------------- #
#  tax_config CRUD (docs/DATA_MODEL.md §5, HANDOFF Q1–Q5)                      #
# --------------------------------------------------------------------------- #
# Each field carries *why it matters*, lifted from docs/TAX.md §2's table, so
# the setup form can explain every unanswered question (docs/phases/PHASE-5 item 1).
CONFIG_FIELD_HELP: dict[str, str] = {
    "has_mortgage": "If yes, interest is relieved only via the 20% Section 24 credit — "
    "typically the largest single number in the computation. Never assumed either way.",
    "annual_mortgage_interest_minor": "From the lender's annual mortgage-interest certificate "
    "(interest only — capital repayments are never relievable). Don't have the exact figure? "
    "Fill in the rate and outstanding balance below instead — Kakeibo estimates it and clearly "
    "flags the number as an estimate, not the certificate figure.",
    "mortgage_rate_pct": "Your mortgage's interest rate (%) — used only when the exact annual "
    "interest above is left blank. Combined with the outstanding balance below to estimate the "
    "year's interest; swap in the real certificate figure once you have it for an exact number.",
    "mortgage_balance_minor": "The mortgage's OUTSTANDING balance right now — not the original "
    "loan amount. Interest is charged on what's left to repay, which shrinks every year on a "
    "repayment mortgage even at a fixed rate, so the original loan amount would overstate it.",
    # Rewritten (docs/phases/PHASE-10-post-launch-fixes.md item 7) — the original wording was
    # technically correct but left a real user unsure whether this asks about their OWN
    # ownership structure of the house or the LETTING arrangement with their tenant. Those are
    # unrelated questions; a house can be owned outright/mortgaged (not leasehold) and still be
    # let to a tenant via an agency, which is the common Scottish case.
    "is_leasehold": '"Leasehold" is about how YOU own this house — do you hold it via a lease '
    "from a separate freeholder, paying them ground rent/service charges (common for flats, "
    "rare for houses)? It has nothing to do with letting the property to a tenant, which is a "
    "separate question. Most Scottish residential property has no leasehold structure (feudal "
    'tenure was abolished in 2004) — if that doesn\'t sound familiar, the answer is almost '
    'certainly "no".',
    "registered_for_sa": "Drives the deadline reminders and the Self Assessment checklist.",
    "utr": "Your Unique Taxpayer Reference, if already registered.",
    "employment_gross_annual_minor": "Places the rental profit in the correct Scottish band — "
    "the marginal rate is likely 21% or 42% depending on salary; guessing misstates the estimate by half.",
    # Also disambiguated (item 7's "skim TAX_FIELD_HELP fully" instruction) — on its own,
    # "monthly rent" could plausibly be misread as rent the user pays on their own home.
    "monthly_rent_minor": "Gross monthly rent you RECEIVE from your tenant (not any rent you pay "
    "yourself) — configures income detection and the Gmail search.",
    "letting_agent": "Agent name — configures the Gmail query for their statements.",
    "agent_fee_pct": "The agent's fee percentage — a recurring allowable expense.",
}


def _get_or_create_config(session: Session, user_id: int) -> TaxConfig:
    cfg = session.get(TaxConfig, user_id)
    if cfg is None:
        cfg = TaxConfig(user_id=user_id, updated_at=now_london().strftime("%Y-%m-%d %H:%M:%S"))
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def _config_dict(cfg: TaxConfig) -> dict:
    return {
        "monthly_rent_minor": cfg.monthly_rent_minor,
        "letting_agent": cfg.letting_agent,
        "agent_fee_pct": cfg.agent_fee_pct,
        "has_mortgage": cfg.has_mortgage,
        "annual_mortgage_interest_minor": cfg.annual_mortgage_interest_minor,
        "mortgage_rate_pct": cfg.mortgage_rate_pct,
        "mortgage_balance_minor": cfg.mortgage_balance_minor,
        "is_leasehold": cfg.is_leasehold,
        "registered_for_sa": cfg.registered_for_sa,
        "utr": cfg.utr,
        "employment_gross_annual_minor": cfg.employment_gross_annual_minor,
        "field_help": CONFIG_FIELD_HELP,
    }


@router.get("/tax/config")
async def get_tax_config(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return {"config": _config_dict(_get_or_create_config(session, user_id))}


class TaxConfigBody(BaseModel):
    monthly_rent_minor: int | None = None
    letting_agent: str | None = None
    agent_fee_pct: float | None = None
    has_mortgage: int | None = None
    annual_mortgage_interest_minor: int | None = None
    mortgage_rate_pct: float | None = None
    mortgage_balance_minor: int | None = None
    is_leasehold: int | None = None
    registered_for_sa: int | None = None
    utr: str | None = None
    employment_gross_annual_minor: int | None = None


@router.put("/tax/config")
async def put_tax_config(
    body: TaxConfigBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    cfg = _get_or_create_config(session, user_id)
    patch = body.model_dump(exclude_unset=True)
    for field in ("has_mortgage", "is_leasehold", "registered_for_sa"):
        if field in patch and patch[field] not in (None, 0, 1):
            raise KakeiboHTTPException(
                status_code=400, detail=f"{field} must be 0, 1, or null", code="invalid_flag"
            )
    for field, value in patch.items():
        setattr(cfg, field, value)
    cfg.updated_at = now_london().strftime("%Y-%m-%d %H:%M:%S")
    session.commit()
    session.refresh(cfg)
    return {"config": _config_dict(cfg)}


# --------------------------------------------------------------------------- #
#  Year figures + summary/estimate (docs/TAX.md §5, docs/API.md §5)           #
# --------------------------------------------------------------------------- #
def _year_figures(session: Session, tax_year: str, is_leasehold: int | None) -> dict:
    """Ledger-derived figures for one year: gross rents, per-type expense
    totals, the allowable-expense subset (mortgage_interest & capital_improvement
    excluded; ground_rent_service only if leasehold — docs/TAX.md §4), and the
    finance costs recorded in the ledger."""
    rows = session.scalars(
        select(RentalLedgerEntry).where(RentalLedgerEntry.tax_year == tax_year)
    ).all()
    gross = sum(r.amount_minor for r in rows if r.kind == "income")
    per_type: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.kind == "expense" and r.expense_type:
            per_type[r.expense_type] += r.amount_minor

    allowable: dict[str, int] = {}
    for etype in ALLOWABLE_EXPENSE_TYPES:
        if etype not in per_type:
            continue
        # ground_rent_service is allowable ONLY on a leasehold property; when
        # leasehold status is unknown/false it's conservatively excluded
        # (overstates tax, never understates — docs/TAX.md §5c principle).
        if etype == "ground_rent_service" and is_leasehold != 1:
            continue
        allowable[etype] = per_type[etype]

    return {
        "gross_rents_minor": gross,
        "allowable_expenses": allowable,
        "allowable_total_minor": sum(allowable.values()),
        "ledger_finance_costs_minor": per_type.get("mortgage_interest", 0),
        "capital_improvements_minor": per_type.get("capital_improvement", 0),
    }


def _resolve_mortgage_interest(cfg: TaxConfig) -> tuple[int | None, str | None]:
    """The exact certificate figure always wins when set (docs/TAX.md §2).
    Otherwise, if BOTH `mortgage_rate_pct` and `mortgage_balance_minor` (the
    OUTSTANDING balance, not the original loan) are set, derive an honest,
    visibly-flagged estimate — never silently invented (docs/TAX.md §0, docs/
    phases/PHASE-10-post-launch-fixes.md item 6). Returns
    ``(annual_mortgage_interest_minor, assumption_or_None)``; the float
    `mortgage_rate_pct` touches money exactly once here, immediately rounded
    to the nearest penny — the one permitted exception to "integer pence
    everywhere" (docs/PLAN.md §6)."""
    if cfg.annual_mortgage_interest_minor is not None:
        return cfg.annual_mortgage_interest_minor, None
    if cfg.mortgage_rate_pct is not None and cfg.mortgage_balance_minor is not None:
        estimated = round(cfg.mortgage_balance_minor * cfg.mortgage_rate_pct / 100)
        return estimated, (
            "Mortgage interest estimated from rate × balance, not your lender's exact "
            "certificate — swap in the real figure once you have it for an exact number."
        )
    return None, None


def _prior_year_pairs(session: Session, tax_year: str, is_leasehold: int | None) -> list[tuple[int, int]]:
    """Chronological ``(gross, allowable)`` pairs for every ledger year strictly
    before ``tax_year`` — feeds loss carry-forward (docs/TAX.md §4). Year keys
    ``YYYY-YY`` sort chronologically as strings within a century."""
    years = sorted(
        {y for (y,) in session.execute(select(RentalLedgerEntry.tax_year).distinct()).all() if y < tax_year}
    )
    pairs: list[tuple[int, int]] = []
    for y in years:
        fig = _year_figures(session, y, is_leasehold)
        pairs.append((fig["gross_rents_minor"], fig["allowable_total_minor"]))
    return pairs


def year_summary_payload(session: Session, user_id: int, tax_year: str) -> dict:
    """Full year summary + estimate (or ``null`` + ``missing_inputs``) —
    shared by `GET /api/tax/years/{tax_year}/summary` and the tax bubble's
    glance inside `GET /api/summary/bubbles`
    (docs/phases/PHASE-7-dashboard.md item 6)."""
    cfg = _get_or_create_config(session, user_id)
    fig = _year_figures(session, tax_year, cfg.is_leasehold)
    resolved_interest_minor, mortgage_assumption = _resolve_mortgage_interest(cfg)

    missing = missing_inputs(
        has_mortgage=cfg.has_mortgage,
        annual_mortgage_interest_minor=resolved_interest_minor,
        employment_gross_annual_minor=cfg.employment_gross_annual_minor,
        ledger_finance_costs_minor=fig["ledger_finance_costs_minor"],
    )

    # profit_minor is shown even before an estimate (docs/DESIGN.md §3b row 6
    # "profit so far") — it's a pure ledger fact, not a tax computation.
    profit_minor = max(0, fig["gross_rents_minor"] - fig["allowable_total_minor"])

    base = {
        "tax_year": tax_year,
        "gross_rents_minor": fig["gross_rents_minor"],
        "allowable_expenses": fig["allowable_expenses"],
        "allowable_total_minor": fig["allowable_total_minor"],
        "finance_costs_minor": fig["ledger_finance_costs_minor"],
        "capital_improvements_minor": fig["capital_improvements_minor"],
        "profit_minor": profit_minor,
        "disclaimer": DISCLAIMER,  # load-bearing: present even when estimate is null
    }

    if missing:
        return {**base, "estimate": None, "missing_inputs": missing}

    rates, assumption = rates_for_year(tax_year)
    finance_costs = (
        resolved_interest_minor if resolved_interest_minor is not None else fig["ledger_finance_costs_minor"]
    )
    loss_bf = loss_brought_forward_minor(_prior_year_pairs(session, tax_year, cfg.is_leasehold))

    assumptions = ([assumption] if assumption else []) + ([mortgage_assumption] if mortgage_assumption else [])
    estimate = estimate_tax(
        EstimateInputs(
            gross_rents_minor=fig["gross_rents_minor"],
            allowable_expenses_minor=fig["allowable_total_minor"],
            finance_costs_minor=finance_costs,
            employment_income_minor=cfg.employment_gross_annual_minor or 0,
            tax_year=tax_year,
            loss_brought_forward_minor=loss_bf,
            tax_at_source_minor=income_tax_minor(cfg.employment_gross_annual_minor or 0, rates),
        ),
        rates,
        assumptions=assumptions,
    )
    return {**base, "estimate": estimate, "missing_inputs": []}


@router.get("/tax/years/{tax_year}/summary")
async def year_summary(
    tax_year: str, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    return year_summary_payload(session, user_id, tax_year)


# --------------------------------------------------------------------------- #
#  Documents review queue (docs/API.md §5, docs/DESIGN.md §4g)                #
# --------------------------------------------------------------------------- #
def _doc_dict(d: TaxDocument) -> dict:
    return {
        "id": d.id,
        "tax_year": d.tax_year,
        "source": d.source,
        "doc_type": d.doc_type,
        "received_at": d.received_at,
        "from_addr": d.from_addr,
        "subject": d.subject,
        "amount_minor": d.amount_minor,
        "amount_confidence": d.amount_confidence,
        "reviewed": bool(d.reviewed),
        "notes": d.notes,
    }


@router.get("/tax/documents")
async def list_documents(
    year: str | None = None,
    unreviewed: int | None = None,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(TaxDocument)
    if year:
        stmt = stmt.where(TaxDocument.tax_year == year)
    if unreviewed:
        stmt = stmt.where(TaxDocument.reviewed == 0)
    # Unreviewed first, then newest — the review queue order (docs/DESIGN.md §4g).
    rows = session.scalars(stmt.order_by(TaxDocument.reviewed, TaxDocument.received_at.desc())).all()
    return {"documents": [_doc_dict(d) for d in rows]}


class DocumentPatchBody(BaseModel):
    doc_type: str | None = None
    amount_minor: int | None = None
    reviewed: int | None = None


@router.patch("/tax/documents/{doc_id}")
async def patch_document(
    doc_id: int,
    body: DocumentPatchBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    doc = session.get(TaxDocument, doc_id)
    if doc is None:
        raise KakeiboHTTPException(status_code=404, detail="Document not found", code="not_found")
    patch = body.model_dump(exclude_unset=True)
    if "doc_type" in patch and patch["doc_type"] not in _DOC_TYPES:
        raise KakeiboHTTPException(status_code=400, detail="Unknown doc_type", code="invalid_doc_type")
    if "doc_type" in patch:
        doc.doc_type = patch["doc_type"]
    if "amount_minor" in patch:
        doc.amount_minor = patch["amount_minor"]
        # A human-entered amount is authoritative — mark it parsed-quality.
        if patch["amount_minor"] is not None:
            doc.amount_confidence = "parsed"
    if "reviewed" in patch:
        doc.reviewed = 1 if patch["reviewed"] else 0
    session.commit()
    return {"document": _doc_dict(doc)}


# --------------------------------------------------------------------------- #
#  rental_ledger (docs/DATA_MODEL.md §6, docs/API.md §5) + CSV export          #
# --------------------------------------------------------------------------- #
def _ledger_dict(e: RentalLedgerEntry) -> dict:
    return {
        "id": e.id,
        "tax_year": e.tax_year,
        "local_date": e.local_date,
        "kind": e.kind,
        "expense_type": e.expense_type,
        "amount_minor": e.amount_minor,
        "source": e.source,
        "transaction_id": e.transaction_id,
        "tax_document_id": e.tax_document_id,
        "notes": e.notes,
    }


class LedgerBody(BaseModel):
    tax_year: str | None = None  # derived from local_date when omitted
    local_date: str
    kind: str
    expense_type: str | None = None
    amount_minor: int
    source: str = "manual"
    transaction_id: int | None = None
    tax_document_id: int | None = None
    notes: str | None = None


@router.post("/tax/ledger", status_code=201)
async def create_ledger_entry(
    body: LedgerBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    if body.kind not in ("income", "expense"):
        raise KakeiboHTTPException(status_code=400, detail="kind must be income or expense", code="invalid_kind")
    if body.kind == "expense":
        if body.expense_type not in _EXPENSE_TYPES:
            raise KakeiboHTTPException(
                status_code=400, detail="expense rows need a valid expense_type", code="invalid_expense_type"
            )
    if body.amount_minor <= 0:
        # Amounts are stored positive; `kind` carries the sign (DATA_MODEL §6).
        raise KakeiboHTTPException(status_code=400, detail="amount_minor must be positive", code="invalid_amount")

    # A ledger row may only link a document that a human has reviewed — parsed
    # mail never silently becomes tax data (docs/API.md §3c; PHASE-5 acceptance).
    if body.tax_document_id is not None:
        doc = session.get(TaxDocument, body.tax_document_id)
        if doc is None:
            raise KakeiboHTTPException(status_code=400, detail="Unknown tax_document_id", code="invalid_document")
        if not doc.reviewed:
            raise KakeiboHTTPException(
                status_code=400,
                detail="Cannot link an unreviewed document — review it first",
                code="document_unreviewed",
            )
    if body.transaction_id is not None:
        txn = session.scalar(
            select(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .where(Transaction.id == body.transaction_id, Account.user_id == user_id)
        )
        if txn is None:
            raise KakeiboHTTPException(status_code=400, detail="Unknown transaction_id", code="invalid_transaction")

    tax_year = body.tax_year or tax_year_of(body.local_date)
    ensure_tax_year(session, tax_year)
    entry = RentalLedgerEntry(
        tax_year=tax_year,
        local_date=body.local_date,
        kind=body.kind,
        expense_type=body.expense_type if body.kind == "expense" else None,
        amount_minor=body.amount_minor,
        source=body.source,
        transaction_id=body.transaction_id,
        tax_document_id=body.tax_document_id,
        notes=body.notes,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return {"entry": _ledger_dict(entry)}


@router.get("/tax/ledger")
async def list_ledger(
    year: str | None = Query(default=None),
    format: str | None = Query(default=None),
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
):
    stmt = select(RentalLedgerEntry)
    if year:
        stmt = stmt.where(RentalLedgerEntry.tax_year == year)
    rows = session.scalars(stmt.order_by(RentalLedgerEntry.local_date, RentalLedgerEntry.id)).all()

    if format == "csv":
        # The accountant-handover CSV (docs/TAX.md §6) — one line per row, with
        # its source-document reference, amount in pounds for a human reader.
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["tax_year", "local_date", "kind", "expense_type", "amount_gbp", "source", "transaction_id", "tax_document_id", "notes"]
        )
        for e in rows:
            writer.writerow(
                [
                    e.tax_year,
                    e.local_date,
                    e.kind,
                    e.expense_type or "",
                    f"{e.amount_minor / 100:.2f}",
                    e.source,
                    e.transaction_id or "",
                    e.tax_document_id or "",
                    (e.notes or "").replace("\n", " "),
                ]
            )
        filename = f"kakeibo-rental-ledger-{year or 'all'}.csv"
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {"entries": [_ledger_dict(e) for e in rows]}


@router.delete("/tax/ledger/{entry_id}")
async def delete_ledger_entry(
    entry_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    entry = session.get(RentalLedgerEntry, entry_id)
    if entry is None:
        raise KakeiboHTTPException(status_code=404, detail="Ledger entry not found", code="not_found")
    session.delete(entry)
    session.commit()
    return {"deleted": True}


# --------------------------------------------------------------------------- #
#  is_rental one-tap ledger candidates (docs/phases/PHASE-5-tax.md item 4)     #
# --------------------------------------------------------------------------- #
@router.get("/tax/candidates")
async def rental_candidates(
    year: str | None = None, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    """``is_rental`` transactions not yet linked into the ledger — offered as
    one-tap add-to-ledger candidates (docs/phases/PHASE-5 item 4)."""
    linked_txn_ids = {
        tid for (tid,) in session.execute(
            select(RentalLedgerEntry.transaction_id).where(RentalLedgerEntry.transaction_id.is_not(None))
        ).all()
    }
    stmt = (
        select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Account.user_id == user_id, Transaction.is_rental == 1)
    )
    rows = session.scalars(stmt.order_by(Transaction.local_date.desc())).all()
    candidates = []
    for t in rows:
        if t.id in linked_txn_ids:
            continue
        if year and tax_year_of(t.local_date) != year:
            continue
        candidates.append(
            {
                "transaction_id": t.id,
                "local_date": t.local_date,
                "counterparty": t.counterparty,
                "reference": t.reference,
                "amount_minor": t.amount_minor,
                "suggested_kind": "income" if t.amount_minor > 0 else "expense",
                "tax_year": tax_year_of(t.local_date),
            }
        )
    return {"candidates": candidates}
