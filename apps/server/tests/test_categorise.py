"""app/engines/categorise.py — pure-function tests, no DB/network
(docs/ARCHITECTURE.md §3: "engines do no I/O"). Fixture data is entirely
synthetic (fake merchants, round amounts).
"""
from __future__ import annotations

from app.engines.categorise import (
    RuleLike,
    categorise,
    default_category_key_for_provider,
    rule_matches,
    should_overwrite,
)

CATEGORY_IDS = {
    "groceries": 1,
    "eating_out": 2,
    "fun": 3,
    "subscriptions": 4,
    "transport": 5,
    "salary": 6,
    "transfer_self": 7,
    "housing": 8,
    "other": 9,
}


def test_default_map_known_category():
    assert default_category_key_for_provider("GROCERIES") == "groceries"
    assert default_category_key_for_provider("groceries") == "groceries", "case-insensitive"


def test_default_map_unknown_category_returns_none():
    assert default_category_key_for_provider("SOME_NEW_STARLING_CATEGORY") is None


def test_default_map_none_input():
    assert default_category_key_for_provider(None) is None


def test_categorise_falls_back_to_provider_default():
    result = categorise(
        spending_category="GROCERIES",
        counterparty="Willow & Pine Grocers",
        reference="GROCERY SHOP",
        rules=[],
        category_id_by_key=CATEGORY_IDS,
    )
    assert result.category_id == CATEGORY_IDS["groceries"]
    assert result.category_source == "provider"
    assert result.is_rental is False
    assert result.exclude_from_spending is False


def test_rule_beats_provider_default_substring_match():
    rules = [
        RuleLike(
            id=1,
            priority=10,
            match_field="counterparty",
            pattern="streamly",
            category_id=CATEGORY_IDS["subscriptions"],
            set_is_rental=False,
            set_exclude=False,
        )
    ]
    result = categorise(
        spending_category="ENTERTAINMENT",
        counterparty="Streamly Plus",
        reference="STREAMLY PLUS SUBSCRIPTION",
        rules=rules,
        category_id_by_key=CATEGORY_IDS,
    )
    assert result.category_id == CATEGORY_IDS["subscriptions"]
    assert result.category_source == "rule"
    assert result.matched_rule_id == 1


def test_rule_regex_pattern():
    rules = [
        RuleLike(
            id=2,
            priority=5,
            match_field="counterparty",
            pattern=r"/^Own .*Transfer$/",
            category_id=CATEGORY_IDS["transfer_self"],
            set_is_rental=False,
            set_exclude=True,
        )
    ]
    result = categorise(
        spending_category="SAVING",
        counterparty="Own Investment Transfer",
        reference="TO T212",
        rules=rules,
        category_id_by_key=CATEGORY_IDS,
    )
    assert result.category_id == CATEGORY_IDS["transfer_self"]
    assert result.category_source == "rule"
    assert result.exclude_from_spending is True


def test_rules_are_first_match_wins_by_priority_not_list_order():
    rules = [
        RuleLike(
            id=20, priority=20, match_field="counterparty", pattern="fern",
            category_id=CATEGORY_IDS["other"], set_is_rental=False, set_exclude=False,
        ),
        RuleLike(
            id=10, priority=10, match_field="counterparty", pattern="fern",
            category_id=CATEGORY_IDS["housing"], set_is_rental=True, set_exclude=False,
        ),
    ]
    result = categorise(
        spending_category="HOME",
        counterparty="Fernbank Renovations",
        reference="INVOICE 42",
        rules=rules,
        category_id_by_key=CATEGORY_IDS,
    )
    assert result.category_id == CATEGORY_IDS["housing"], "lower priority number must win, regardless of list order"
    assert result.is_rental is True


def test_rule_matches_is_case_insensitive_substring():
    rule = RuleLike(id=1, priority=1, match_field="reference", pattern="invoice", category_id=1, set_is_rental=False, set_exclude=False)
    assert rule_matches(rule, counterparty=None, reference="INVOICE 42", provider_category=None) is True


def test_rule_matches_false_when_field_absent():
    rule = RuleLike(id=1, priority=1, match_field="reference", pattern="invoice", category_id=1, set_is_rental=False, set_exclude=False)
    assert rule_matches(rule, counterparty="Fernbank", reference=None, provider_category=None) is False


def test_should_overwrite_manual_is_never_overwritten():
    assert should_overwrite("manual", "rule") is False
    assert should_overwrite("manual", "provider") is False
    assert should_overwrite("manual", "manual") is False


def test_should_overwrite_rule_beats_provider():
    assert should_overwrite("provider", "rule") is True
    assert should_overwrite("rule", "provider") is False


def test_should_overwrite_same_rank_refreshes():
    assert should_overwrite("provider", "provider") is True
    assert should_overwrite("rule", "rule") is True


def test_should_overwrite_no_existing_row():
    assert should_overwrite(None, "provider") is True
