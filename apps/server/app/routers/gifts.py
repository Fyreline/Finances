"""Gift-occasion budgets — docs/PLAN.md §3 row 10, docs/phases/
PHASE-9-personal-goals.md §4. CRUD for occasions + items; each occasion's
rollup comes from `engines/gifts.py`, and any item can also carry goal 11's
affordability verdict (`engines/affordability.py`) checked against the
*occasion's own remaining budget* instead of general safe-to-spend headroom —
"share the mechanic, don't build two separate systems". A gift item never
touches a savings-goal projection (it's scoped to its occasion's own limit,
not the general pot), so `goal_projection_before`/`_after` are always `None`
here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..engines.affordability import check_affordability
from ..engines.gifts import occasion_summary
from ..errors import KakeiboHTTPException
from ..models import GiftItem, GiftOccasion

router = APIRouter(prefix="/gifts", tags=["gifts"])


def _item_dict(item: GiftItem) -> dict:
    return {
        "id": item.id,
        "occasion_id": item.occasion_id,
        "label": item.label,
        "price_minor": item.price_minor,
        "bought": bool(item.bought),
        "bought_date": item.bought_date,
    }


def _occasion_dict(session: Session, occasion: GiftOccasion) -> dict:
    items = session.scalars(
        select(GiftItem).where(GiftItem.occasion_id == occasion.id).order_by(GiftItem.id)
    ).all()
    summary = occasion_summary(occasion.limit_minor, [i.price_minor for i in items])
    return {
        "id": occasion.id,
        "label": occasion.label,
        "limit_minor": occasion.limit_minor,
        "target_date": occasion.target_date,
        "items": [_item_dict(i) for i in items],
        **summary,
    }


def gifts_payload(session: Session, user_id: int) -> dict:
    occasions = session.scalars(
        select(GiftOccasion).where(GiftOccasion.user_id == user_id).order_by(GiftOccasion.id)
    ).all()
    return {"occasions": [_occasion_dict(session, o) for o in occasions]}


def _get_owned_occasion(session: Session, user_id: int, occasion_id: int) -> GiftOccasion:
    occasion = session.scalar(
        select(GiftOccasion).where(GiftOccasion.id == occasion_id, GiftOccasion.user_id == user_id)
    )
    if occasion is None:
        raise KakeiboHTTPException(status_code=404, detail="Occasion not found", code="not_found")
    return occasion


def _get_owned_item(session: Session, user_id: int, item_id: int) -> GiftItem:
    item = session.scalar(
        select(GiftItem)
        .join(GiftOccasion, GiftItem.occasion_id == GiftOccasion.id)
        .where(GiftItem.id == item_id, GiftOccasion.user_id == user_id)
    )
    if item is None:
        raise KakeiboHTTPException(status_code=404, detail="Item not found", code="not_found")
    return item


@router.get("/occasions")
async def list_occasions(user_id: int = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    return gifts_payload(session, user_id)


class OccasionCreateBody(BaseModel):
    label: str
    limit_minor: int | None = None
    target_date: str | None = None


@router.post("/occasions", status_code=201)
async def create_occasion(
    body: OccasionCreateBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    if body.limit_minor is not None and body.limit_minor < 0:
        raise KakeiboHTTPException(status_code=400, detail="limit_minor must not be negative", code="invalid_limit")
    occasion = GiftOccasion(user_id=user_id, label=body.label, limit_minor=body.limit_minor, target_date=body.target_date)
    session.add(occasion)
    session.commit()
    session.refresh(occasion)
    return {"occasion": _occasion_dict(session, occasion)}


class OccasionPatchBody(BaseModel):
    label: str | None = None
    limit_minor: int | None = None
    target_date: str | None = None


@router.patch("/occasions/{occasion_id}")
async def patch_occasion(
    occasion_id: int,
    body: OccasionPatchBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    occasion = _get_owned_occasion(session, user_id, occasion_id)
    patch = body.model_dump(exclude_unset=True)
    if "limit_minor" in patch and patch["limit_minor"] is not None and patch["limit_minor"] < 0:
        raise KakeiboHTTPException(status_code=400, detail="limit_minor must not be negative", code="invalid_limit")
    for field, value in patch.items():
        setattr(occasion, field, value)
    session.commit()
    session.refresh(occasion)
    return {"occasion": _occasion_dict(session, occasion)}


@router.delete("/occasions/{occasion_id}")
async def delete_occasion(
    occasion_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    occasion = _get_owned_occasion(session, user_id, occasion_id)
    for item in session.scalars(select(GiftItem).where(GiftItem.occasion_id == occasion.id)).all():
        session.delete(item)
    session.delete(occasion)
    session.commit()
    return {"deleted": True}


class ItemCreateBody(BaseModel):
    label: str
    price_minor: int


@router.post("/occasions/{occasion_id}/items", status_code=201)
async def create_item(
    occasion_id: int,
    body: ItemCreateBody,
    user_id: int = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    occasion = _get_owned_occasion(session, user_id, occasion_id)
    if body.price_minor <= 0:
        raise KakeiboHTTPException(status_code=400, detail="price_minor must be positive", code="invalid_price")
    item = GiftItem(occasion_id=occasion.id, label=body.label, price_minor=body.price_minor)
    session.add(item)
    session.commit()
    return {"occasion": _occasion_dict(session, occasion)}


class ItemPatchBody(BaseModel):
    label: str | None = None
    price_minor: int | None = None
    bought: bool | None = None
    bought_date: str | None = None


@router.patch("/items/{item_id}")
async def patch_item(
    item_id: int, body: ItemPatchBody, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    item = _get_owned_item(session, user_id, item_id)
    patch = body.model_dump(exclude_unset=True)
    if "price_minor" in patch and patch["price_minor"] is not None and patch["price_minor"] <= 0:
        raise KakeiboHTTPException(status_code=400, detail="price_minor must be positive", code="invalid_price")
    if "label" in patch and patch["label"] is not None:
        item.label = patch["label"]
    if "price_minor" in patch and patch["price_minor"] is not None:
        item.price_minor = patch["price_minor"]
    if "bought" in patch and patch["bought"] is not None:
        item.bought = int(patch["bought"])
    if "bought_date" in patch:
        item.bought_date = patch["bought_date"]
    session.commit()
    occasion = session.get(GiftOccasion, item.occasion_id)
    return {"occasion": _occasion_dict(session, occasion)}


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    item = _get_owned_item(session, user_id, item_id)
    session.delete(item)
    session.commit()
    return {"deleted": True}


@router.get("/items/{item_id}/affordability")
async def item_affordability(
    item_id: int, user_id: int = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    """Goal 11's shared mechanic (docs/phases/PHASE-9-personal-goals.md §4):
    the occasion's remaining budget *excluding this item's own price* stands
    in for general safe-to-spend headroom."""
    item = _get_owned_item(session, user_id, item_id)
    occasion = session.get(GiftOccasion, item.occasion_id)
    other_items = session.scalars(
        select(GiftItem).where(GiftItem.occasion_id == occasion.id, GiftItem.id != item.id)
    ).all()
    summary = occasion_summary(occasion.limit_minor, [i.price_minor for i in other_items])
    return check_affordability(item.price_minor, summary["remaining_minor"], None, None)
