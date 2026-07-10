"""Transactions, categories, and category rules — docs/API.md §5 "Transactions"
section. One router module per docs/ARCHITECTURE.md's repo layout (only
`routers/transactions.py` is listed there for this whole group — categories
and rules are small enough to share it rather than inventing extra files the
docs don't mention).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..engines.categorise import RuleLike, rule_matches, should_overwrite
from ..errors import KakeiboHTTPException
from ..models import Account, Category, CategoryRule, Transaction

router = APIRouter(tags=["transactions"])

PAGE_SIZE = 50
_MATCH_FIELDS = {"counterparty", "reference", "provider_category"}


# ---------------------------------------------------------------- serialisers
def _category_brief(cat: Category | None) -> dict | None:
    if cat is None:
        return None
    return {"id": cat.id, "key": cat.key, "label": cat.label}


def _category_dict(cat: Category) -> dict:
    return {
        "id": cat.id,
        "key": cat.key,
        "label": cat.label,
        "kind": cat.kind,
        "viz_slot": cat.viz_slot,
        "sort": cat.sort,
    }


def _rule_dict(rule: CategoryRule) -> dict:
    return {
        "id": rule.id,
        "priority": rule.priority,
        "match_field": rule.match_field,
        "pattern": rule.pattern,
        "category_id": rule.category_id,
        "set_is_rental": bool(rule.set_is_rental),
        "set_exclude": bool(rule.set_exclude),
    }


def _transaction_dict(txn: Transaction, categories_by_id: dict[int, Category]) -> dict:
    return {
        "id": txn.id,
        "local_date": txn.local_date,
        "counterparty": txn.counterparty,
        "reference": txn.reference,
        "amount_minor": txn.amount_minor,
        "category": _category_brief(categories_by_id.get(txn.category_id) if txn.category_id else None),
        "category_source": txn.category_source,
        "is_rental": bool(txn.is_rental),
        "exclude_from_spending": bool(txn.exclude_from_spending),
        "settled": bool(txn.settled),
    }


# --------------------------------------------------------------- transactions
@router.get("/transactions")
async def list_transactions(
    month: str | None = None,
    category: str | None = None,
    account: int | None = None,
    q: str | None = None,
    page: int = 1,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(Transaction).join(Account, Transaction.account_id == Account.id).where(Account.user_id == user_id)
    if month:
        stmt = stmt.where(Transaction.local_date.like(f"{month}-%"))
    if category:
        stmt = stmt.join(Category, Transaction.category_id == Category.id).where(Category.key == category)
    if account:
        stmt = stmt.where(Transaction.account_id == account)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Transaction.counterparty.ilike(like), Transaction.reference.ilike(like)))

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    page = max(page, 1)
    rows = session.scalars(
        stmt.order_by(Transaction.local_date.desc(), Transaction.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()

    categories_by_id = {c.id: c for c in session.scalars(select(Category)).all()}
    return {
        "items": [_transaction_dict(t, categories_by_id) for t in rows],
        "total": total,
        "page_size": PAGE_SIZE,
    }


class TransactionPatchBody(BaseModel):
    category_id: int | None = None
    is_rental: bool | None = None
    exclude_from_spending: bool | None = None


@router.patch("/transactions/{transaction_id}")
async def patch_transaction(
    transaction_id: int,
    body: TransactionPatchBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    txn = session.scalar(
        select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Transaction.id == transaction_id, Account.user_id == user_id)
    )
    if txn is None:
        raise KakeiboHTTPException(status_code=404, detail="Transaction not found", code="not_found")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise KakeiboHTTPException(status_code=400, detail="No fields to update", code="empty_patch")

    if "category_id" in patch:
        new_category_id = patch["category_id"]
        if new_category_id is not None and session.get(Category, new_category_id) is None:
            raise KakeiboHTTPException(status_code=400, detail="Unknown category", code="invalid_category")
        txn.category_id = new_category_id
    if "is_rental" in patch:
        txn.is_rental = 1 if patch["is_rental"] else 0
    if "exclude_from_spending" in patch:
        txn.exclude_from_spending = 1 if patch["exclude_from_spending"] else 0

    # Any PATCH is a manual override — never overwritten by a later re-sync
    # or rules retro-apply (docs/API.md §5, docs/DATA_MODEL.md §2).
    txn.category_source = "manual"
    session.commit()
    session.refresh(txn)

    categories_by_id = {c.id: c for c in session.scalars(select(Category)).all()}
    return {"transaction": _transaction_dict(txn, categories_by_id)}


# ----------------------------------------------------------------- categories
@router.get("/categories")
async def list_categories(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(Category).order_by(Category.sort)).all()
    return {"categories": [_category_dict(c) for c in rows]}


# --------------------------------------------------------------------- rules
class RuleBody(BaseModel):
    priority: int
    match_field: str
    pattern: str
    category_id: int
    set_is_rental: bool = False
    set_exclude: bool = False


class RulePatchBody(BaseModel):
    priority: int | None = None
    match_field: str | None = None
    pattern: str | None = None
    category_id: int | None = None
    set_is_rental: bool | None = None
    set_exclude: bool | None = None


def _validate_match_field(match_field: str) -> None:
    if match_field not in _MATCH_FIELDS:
        raise KakeiboHTTPException(
            status_code=400,
            detail=f"match_field must be one of {sorted(_MATCH_FIELDS)}",
            code="invalid_match_field",
        )


def _validate_category(session: Session, category_id: int) -> None:
    if session.get(Category, category_id) is None:
        raise KakeiboHTTPException(status_code=400, detail="Unknown category", code="invalid_category")


@router.get("/rules")
async def list_rules(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(CategoryRule).order_by(CategoryRule.priority)).all()
    return {"rules": [_rule_dict(r) for r in rows]}


@router.post("/rules", status_code=201)
async def create_rule(
    body: RuleBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    _validate_match_field(body.match_field)
    _validate_category(session, body.category_id)
    rule = CategoryRule(
        priority=body.priority,
        match_field=body.match_field,
        pattern=body.pattern,
        category_id=body.category_id,
        set_is_rental=1 if body.set_is_rental else 0,
        set_exclude=1 if body.set_exclude else 0,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return {"rule": _rule_dict(rule)}


@router.patch("/rules/{rule_id}")
async def patch_rule(
    rule_id: int,
    body: RulePatchBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    rule = session.get(CategoryRule, rule_id)
    if rule is None:
        raise KakeiboHTTPException(status_code=404, detail="Rule not found", code="not_found")

    patch = body.model_dump(exclude_unset=True)
    if "match_field" in patch:
        _validate_match_field(patch["match_field"])
    if "category_id" in patch:
        _validate_category(session, patch["category_id"])

    for field in ("priority", "match_field", "pattern", "category_id"):
        if field in patch:
            setattr(rule, field, patch[field])
    if "set_is_rental" in patch:
        rule.set_is_rental = 1 if patch["set_is_rental"] else 0
    if "set_exclude" in patch:
        rule.set_exclude = 1 if patch["set_exclude"] else 0

    session.commit()
    session.refresh(rule)
    return {"rule": _rule_dict(rule)}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    rule = session.get(CategoryRule, rule_id)
    if rule is None:
        raise KakeiboHTTPException(status_code=404, detail="Rule not found", code="not_found")
    session.delete(rule)
    session.commit()
    return {"deleted": True}


@router.post("/rules/{rule_id}/apply")
async def apply_rule(
    rule_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    """Retro-apply one rule to every existing transaction it matches —
    respects manual rank: a transaction whose `category_source` is already
    `manual` is skipped entirely (docs/phases/PHASE-2-starling.md acceptance:
    "a manual recategorisation survives ... a rules retro-apply")."""
    rule = session.get(CategoryRule, rule_id)
    if rule is None:
        raise KakeiboHTTPException(status_code=404, detail="Rule not found", code="not_found")

    rule_like = RuleLike(
        id=rule.id,
        priority=rule.priority,
        match_field=rule.match_field,
        pattern=rule.pattern,
        category_id=rule.category_id,
        set_is_rental=bool(rule.set_is_rental),
        set_exclude=bool(rule.set_exclude),
    )

    txns = session.scalars(
        select(Transaction).join(Account, Transaction.account_id == Account.id).where(Account.user_id == user_id)
    ).all()

    recategorised = 0
    for txn in txns:
        if not should_overwrite(txn.category_source, "rule"):
            continue
        if not rule_matches(
            rule_like, counterparty=txn.counterparty, reference=txn.reference, provider_category=txn.provider_category
        ):
            continue
        txn.category_id = rule.category_id
        txn.category_source = "rule"
        txn.is_rental = 1 if rule.set_is_rental else 0
        txn.exclude_from_spending = 1 if rule.set_exclude else 0
        recategorised += 1

    session.commit()
    return {"recategorised": recategorised}
