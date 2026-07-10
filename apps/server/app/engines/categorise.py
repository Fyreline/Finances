"""Categorisation engine — docs/API.md §6b, docs/DATA_MODEL.md §2/§3.

Pure functions only (docs/ARCHITECTURE.md §3: "engines do no I/O; routers
assemble inputs and call them") — this module never touches a Session or the
network. Two inputs feed a transaction's category: Starling's own
``spendingCategory`` (a default, best-effort mapping) and the user's ordered
``category_rules`` (first-match-wins, always beats the provider default).
Precedence when *re*-categorising (a re-sync or a rules retro-apply) is
``manual > rule > provider`` — a manual assignment is never overwritten
(docs/DATA_MODEL.md §2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Starling's `spendingCategory` feed field -> Kakeibo's own category `key`
# (docs/DATA_MODEL.md §3 taxonomy). ⚠️ verify against a live account: this is
# a best-effort mapping built from Starling's publicly documented category
# set, not confirmed against a real feed response (no PAT exists yet,
# docs/SECRETS.md) — correct it here the day a real account's feed reveals a
# spelling or value this map doesn't recognise; unmapped/unknown values fall
# through to `None` (transaction stays uncategorised, never guessed).
STARLING_CATEGORY_MAP: dict[str, str] = {
    "GROCERIES": "groceries",
    "EATING_OUT": "eating_out",
    "TAKEAWAY": "eating_out",
    "ENTERTAINMENT": "fun",
    "SHOPPING": "shopping",
    "TRANSPORT": "transport",
    "BILLS_AND_SERVICES": "bills",
    "PHONE_INTERNET_AND_TV": "bills",
    "INSURANCE": "bills",
    "RENT": "housing",
    "MORTGAGE": "housing",
    "HOME": "housing",
    "GIFTS": "gifts",
    "FAMILY": "gifts",
    "PETS": "other",
    "HOLIDAY": "holidays",
    "GENERAL": "other",
    "LIFESTYLE": "fun",
    "INCOME": "salary",
    "SAVING": "savings_transfer",
    "PAYMENTS": "other",
    "CHARITY": "gifts",
    "LOAN": "bills",
    "CASH": "other",
    "FINANCIAL_AND_LEGAL_SERVICES": "other",
    "OTHER": "other",
    "NONE": "other",
}

# category_source rank — higher survives a re-categorisation pass
# (docs/DATA_MODEL.md §2: "manual is never overwritten...rule beats provider").
_SOURCE_RANK = {"provider": 0, "rule": 1, "manual": 2}


@dataclass(frozen=True)
class RuleLike:
    """Structural shape the engine needs from a `category_rules` row —
    callers pass the real ORM row (or a test double) positionally-compatible
    with this; kept separate from `app.models` so this module stays
    import-light and DB-free."""

    id: int
    priority: int
    match_field: str  # 'counterparty' | 'reference' | 'provider_category'
    pattern: str
    category_id: int
    set_is_rental: bool
    set_exclude: bool


@dataclass(frozen=True)
class CategoryResult:
    category_id: int | None
    category_source: str  # 'provider' | 'rule'
    is_rental: bool
    exclude_from_spending: bool
    matched_rule_id: int | None = None


def default_category_key_for_provider(spending_category: str | None) -> str | None:
    """Starling `spendingCategory` -> Kakeibo category `key`, or None if
    absent/unrecognised (never guesses)."""
    if not spending_category:
        return None
    return STARLING_CATEGORY_MAP.get(spending_category.strip().upper())


def _field_value(rule: RuleLike, *, counterparty: str | None, reference: str | None, provider_category: str | None) -> str | None:
    return {
        "counterparty": counterparty,
        "reference": reference,
        "provider_category": provider_category,
    }.get(rule.match_field)


def rule_matches(rule: RuleLike, *, counterparty: str | None, reference: str | None, provider_category: str | None) -> bool:
    """Case-insensitive substring match by default; `/pattern/` (regex
    delimiters) switches to a case-insensitive regex search
    (docs/DATA_MODEL.md §3: 'case-insensitive substring or /regex/')."""
    value = _field_value(rule, counterparty=counterparty, reference=reference, provider_category=provider_category)
    if not value:
        return False
    pattern = rule.pattern
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        try:
            return re.search(pattern[1:-1], value, re.IGNORECASE) is not None
        except re.error:
            return False
    return pattern.lower() in value.lower()


def categorise(
    *,
    spending_category: str | None,
    counterparty: str | None,
    reference: str | None,
    rules: list[RuleLike],
    category_id_by_key: dict[str, int],
) -> CategoryResult:
    """First-match-wins over `rules` (caller passes them pre-ordered by
    `priority` ascending), else the Starling default map, else uncategorised.
    """
    for rule in sorted(rules, key=lambda r: r.priority):
        if rule_matches(rule, counterparty=counterparty, reference=reference, provider_category=spending_category):
            return CategoryResult(
                category_id=rule.category_id,
                category_source="rule",
                is_rental=bool(rule.set_is_rental),
                exclude_from_spending=bool(rule.set_exclude),
                matched_rule_id=rule.id,
            )

    key = default_category_key_for_provider(spending_category)
    category_id = category_id_by_key.get(key) if key else None
    return CategoryResult(category_id=category_id, category_source="provider", is_rental=False, exclude_from_spending=False)


def should_overwrite(existing_source: str | None, new_source: str) -> bool:
    """Whether a categorisation pass tagged `new_source` is allowed to
    overwrite a row currently tagged `existing_source`. A `manual` row is
    never overwritten by anything; otherwise higher-or-equal rank wins
    (docs/DATA_MODEL.md §2 — "re-running categorisation only touches rows
    whose source is below the assigner's rank", equal rank included so a
    re-sync/rules-reload can refresh its own prior work)."""
    if existing_source is None:
        return True
    if existing_source == "manual":
        return False
    return _SOURCE_RANK[new_source] >= _SOURCE_RANK[existing_source]
