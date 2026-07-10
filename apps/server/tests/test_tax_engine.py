"""The SA estimator — docs/TAX.md §5, app/engines/tax.py.

**These tests ARE the audit trail** (docs/TAX.md §7, docs/phases/PHASE-5 item 3):
the three §5d worked examples are pinned with every figure hand-computed in a
comment, the band-straddling case exact to the penny. All figures are the
docs' own *illustrative* placeholders (docs/TAX.md §5d "none of these are the
user's real figures") — no real personal number is committed here.
"""
from __future__ import annotations

from app.engines.tax import (
    ALLOWABLE_EXPENSE_TYPES,
    DISCLAIMER,
    EXCLUDED_FROM_EXPENSES,
    METHOD_ALLOWANCE,
    METHOD_EXPENSES,
    EstimateInputs,
    estimate_tax,
    loss_brought_forward_minor,
    missing_inputs,
    payments_on_account,
)
from app.engines.tax_rates import SCOTTISH_2025_26

R = SCOTTISH_2025_26


# --------------------------------------------------------------------------- #
#  The three docs/TAX.md §5d worked examples                                   #
# --------------------------------------------------------------------------- #
def test_worked_example_expenses_route_wins():
    # docs/TAX.md §5d, verbatim illustrative config:
    #   rent £850/mo × 12 = £10,200 gross ; agent 10% £1,020 + insurance £240 +
    #   repair £600 = £1,860 allowable ; mortgage interest £3,600 ;
    #   employment £48,000 ; Scottish 2025-26 ; no loss b/f.
    #
    # Route 1: profit = 10,200 − 1,860         = £8,340
    #          £48,000 already > £43,662 → all profit in higher band:
    #          tax on profit = 8,340 × 42%     = £3,502.80
    #          s24 = 20% × min(3,600,8,340,·)  = £720.00
    #          tax due = 3,502.80 − 720.00      = £2,782.80
    # Route 2: profit = 10,200 − 1,000 = £9,200 ; 9,200 × 42% = £3,864.00 ; no credit
    # Engine: method = expenses_plus_s24, tax_due 278280, s24 72000 (matches §5d).
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=1_020_000,
            allowable_expenses_minor=186_000,
            finance_costs_minor=360_000,
            employment_income_minor=4_800_000,
            tax_year="2026-27",
        ),
        R,
    )
    assert est["method_used"] == METHOD_EXPENSES
    assert est["tax_due_minor"] == 278_280
    assert est["s24_credit_minor"] == 72_000
    assert est["marginal_band"] == "higher"
    assert est["comparison"][METHOD_EXPENSES]["profit_minor"] == 834_000
    assert est["comparison"][METHOD_EXPENSES]["tax_on_profit_minor"] == 350_280
    assert est["comparison"][METHOD_ALLOWANCE]["tax_due_minor"] == 386_400


def test_worked_example_band_straddle():
    # Second pinned case (docs/TAX.md §5d "must cover band-straddling"):
    #   employment £41,000 ; rent £1,000/mo × 12 = £12,000 gross ;
    #   agent £1,200 + insurance £300 = £1,500 allowable ; mortgage interest £2,000.
    #
    # Route 1: profit = 12,000 − 1,500 = £10,500, stacked on £41,000 straddles £43,662:
    #          intermediate slice 43,662 − 41,000 = 2,662 × 21% = £559.02
    #          higher slice       51,500 − 43,662 = 7,838 × 42% = £3,291.96
    #          tax on profit                                    = £3,850.98
    #          s24 = 20% × min(2,000, 10,500, ·)                = £400.00
    #          tax due = 3,850.98 − 400.00                      = £3,450.98
    # Route 2: profit = 12,000 − 1,000 = £11,000 stacked on £41,000:
    #          intermediate 2,662 × 21% + higher 8,338 × 42%
    #          = 559.02 + 3,501.96 = £4,060.98 ; no credit
    # Engine: expenses route wins, tax_due 345098 — exact to the penny.
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=1_200_000,
            allowable_expenses_minor=150_000,
            finance_costs_minor=200_000,
            employment_income_minor=4_100_000,
            tax_year="2026-27",
        ),
        R,
    )
    assert est["method_used"] == METHOD_EXPENSES
    assert est["comparison"][METHOD_EXPENSES]["tax_on_profit_minor"] == 385_098
    assert est["comparison"][METHOD_EXPENSES]["s24_credit_minor"] == 40_000
    assert est["tax_due_minor"] == 345_098
    assert est["comparison"][METHOD_ALLOWANCE]["tax_due_minor"] == 406_098
    assert est["marginal_band"] == "higher"


def test_worked_example_property_allowance_wins():
    # Third pinned case (docs/TAX.md §5d "the allowance winning: expenses £300,
    # no mortgage"):
    #   employment £48,000 ; rent £500/mo × 12 = £6,000 gross ; £300 expenses ; no mortgage.
    #
    # Route 1: profit = 6,000 − 300 = £5,700 (all higher) → 5,700 × 42% = £2,394.00 ; no s24
    # Route 2: profit = 6,000 − 1,000 = £5,000 → 5,000 × 42% = £2,100.00
    # Engine: allowance wins (2,100 < 2,394), tax_due 210000, s24 0.
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=600_000,
            allowable_expenses_minor=30_000,
            finance_costs_minor=0,
            employment_income_minor=4_800_000,
            tax_year="2026-27",
        ),
        R,
    )
    assert est["method_used"] == METHOD_ALLOWANCE
    assert est["tax_due_minor"] == 210_000
    assert est["s24_credit_minor"] == 0
    assert est["comparison"][METHOD_EXPENSES]["tax_due_minor"] == 239_400


def test_property_allowance_full_relief_under_1000():
    # gross ≤ £1,000 → full relief, no tax (docs/TAX.md §5c).
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=80_000,  # £800
            allowable_expenses_minor=0,
            finance_costs_minor=0,
            employment_income_minor=4_800_000,
            tax_year="2026-27",
        ),
        R,
    )
    assert est["method_used"] == METHOD_ALLOWANCE
    assert est["tax_due_minor"] == 0
    assert est["comparison"][METHOD_ALLOWANCE]["profit_minor"] == 0


# --------------------------------------------------------------------------- #
#  Never-guess gating (docs/TAX.md §0 rule 2, §7)                              #
# --------------------------------------------------------------------------- #
def test_missing_inputs_flags_unset_required_fields():
    # has_mortgage unknown → flagged; employment unknown → flagged.
    assert missing_inputs(
        has_mortgage=None, annual_mortgage_interest_minor=None, employment_gross_annual_minor=None
    ) == ["has_mortgage", "employment_gross_annual"]

    # Mortgage present but its interest figure unset AND no ledger rows → flagged.
    assert missing_inputs(
        has_mortgage=1, annual_mortgage_interest_minor=None, employment_gross_annual_minor=4_800_000
    ) == ["annual_mortgage_interest"]

    # Mortgage present, interest satisfied by actual ledger rows → not flagged.
    assert missing_inputs(
        has_mortgage=1,
        annual_mortgage_interest_minor=None,
        employment_gross_annual_minor=4_800_000,
        ledger_finance_costs_minor=360_000,
    ) == []

    # No mortgage + employment known → nothing missing (fully answerable).
    assert missing_inputs(
        has_mortgage=0, annual_mortgage_interest_minor=None, employment_gross_annual_minor=4_800_000
    ) == []


# --------------------------------------------------------------------------- #
#  NIC, disclaimer, expense taxonomy                                           #
# --------------------------------------------------------------------------- #
def test_nic_is_zero_with_explanation_and_disclaimer_present():
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=1_020_000,
            allowable_expenses_minor=186_000,
            finance_costs_minor=360_000,
            employment_income_minor=4_800_000,
            tax_year="2026-27",
        ),
        R,
    )
    assert est["nic_due_minor"] == 0
    assert "not a trade" in est["nic_note"]
    assert est["disclaimer"] == DISCLAIMER  # load-bearing on every estimate


def test_mortgage_interest_and_capital_are_not_allowable_types():
    # docs/TAX.md §4: mortgage_interest feeds S24 only; capital_improvement is
    # allowable nowhere. Neither is in the allowable-expense set.
    assert "mortgage_interest" in EXCLUDED_FROM_EXPENSES
    assert "capital_improvement" in EXCLUDED_FROM_EXPENSES
    assert not (EXCLUDED_FROM_EXPENSES & ALLOWABLE_EXPENSE_TYPES)


# --------------------------------------------------------------------------- #
#  Loss carry-forward, POA, assumptions                                        #
# --------------------------------------------------------------------------- #
def test_loss_brought_forward_carries_and_absorbs():
    # A loss year (expenses £8,000 > rents £5,000) carries £3,000 forward.
    assert loss_brought_forward_minor([(500_000, 800_000)]) == 300_000
    # A later profit of £15,000 absorbs the £3,000 loss fully → nothing carries on.
    assert loss_brought_forward_minor([(500_000, 800_000), (2_000_000, 500_000)]) == 0


def test_loss_brought_forward_reduces_taxable_profit():
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=1_020_000,
            allowable_expenses_minor=186_000,
            finance_costs_minor=0,
            employment_income_minor=4_800_000,
            tax_year="2026-27",
            loss_brought_forward_minor=334_000,  # £3,340 loss b/f
        ),
        R,
    )
    # profit = 10,200 − 1,860 − 3,340 = £5,000 (vs £8,340 without the loss).
    assert est["comparison"][METHOD_EXPENSES]["profit_minor"] == 500_000


def test_payments_on_account_test():
    # Not required — bill ≤ £1,000.
    low = payments_on_account(sa_tax_due_minor=50_000, tax_at_source_minor=800_000, tax_year="2025-26")
    assert low["required"] is False

    # Required — £3,000 bill, only 62.5% collected at source (< 80%).
    hi = payments_on_account(sa_tax_due_minor=300_000, tax_at_source_minor=500_000, tax_year="2025-26")
    assert hi["required"] is True
    assert hi["amounts_minor"] == [150_000, 150_000]  # two halves, sum to the bill exactly
    assert hi["dates"] == ["2027-01-31", "2027-07-31"]

    # Not required — £3,000 bill but 96.8% collected at source (≥ 80%).
    at_source = payments_on_account(sa_tax_due_minor=300_000, tax_at_source_minor=9_000_000, tax_year="2025-26")
    assert at_source["required"] is False


def test_assumptions_pass_through_to_estimate():
    est = estimate_tax(
        EstimateInputs(
            gross_rents_minor=600_000,
            allowable_expenses_minor=30_000,
            finance_costs_minor=0,
            employment_income_minor=4_800_000,
            tax_year="2026-27",
        ),
        R,
        assumptions=["2026-27 Scottish rates not yet entered — using 2025-26"],
    )
    assert est["assumptions"] == ["2026-27 Scottish rates not yet entered — using 2025-26"]
