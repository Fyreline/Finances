"""Scottish rate-table maths — docs/TAX.md §3, app/engines/tax_rates.py.

These pin the band widths against docs/TAX.md §3's *total-income* table (the
two representations must agree at every band edge), the personal-allowance
taper, and the marginal-band lookup. Every figure is hand-computed in a comment
— these tests are part of the estimator's audit trail (docs/TAX.md §7).
"""
from __future__ import annotations

from app.engines.tax_rates import (
    SCOTTISH_2025_26,
    income_tax_minor,
    marginal_band_name,
    personal_allowance_minor,
    rates_for_year,
)

R = SCOTTISH_2025_26


def test_band_edges_match_taxmd_section3_total_income_table():
    # docs/TAX.md §3 quotes bands as TOTAL income (incl. PA). Tax at each quoted
    # upper edge, hand-computed, must equal income_tax_minor at that income:
    #   £12,570 (top of PA)      → £0.00
    assert income_tax_minor(1_257_000, R) == 0
    #   £15,397 (top of starter) → 2,827 × 19%            = £537.13
    assert income_tax_minor(1_539_700, R) == 53_713
    #   £27,491 (top of basic)   → 537.13 + 12,094 × 20%  = £2,955.93
    assert income_tax_minor(2_749_100, R) == 295_593
    #   £43,662 (top of interm.) → 2,955.93 + 16,171×21%  = £6,351.84
    #     16,171 × 21% = £3,395.91 ; 2,955.93 + 3,395.91  = £6,351.84
    assert income_tax_minor(4_366_200, R) == 635_184


def test_income_tax_48000_higher_band():
    # £48,000: taxable 35,430 =
    #   starter 2,827×19% = 537.13
    #   basic  12,094×20% = 2,418.80
    #   interm 16,171×21% = 3,395.91
    #   higher  4,338×42% = 1,821.96   (35,430 − 31,092 = 4,338)
    #   total             = £8,173.80
    assert income_tax_minor(4_800_000, R) == 817_380


def test_marginal_stacking_is_exact_across_a_band():
    # £48,000 + £8,340 profit lands wholly in the higher (42%) band:
    #   tax(56,340) − tax(48,000) = 8,340 × 42% = £3,502.80
    assert income_tax_minor(5_634_000, R) - income_tax_minor(4_800_000, R) == 350_280


def test_marginal_stacking_straddles_intermediate_and_higher():
    # £41,000 + £10,500 profit straddles the £43,662 boundary:
    #   intermediate slice 43,662 − 41,000 = 2,662 × 21% = £559.02
    #   higher slice       51,500 − 43,662 = 7,838 × 42% = £3,291.96
    #   total                                            = £3,850.98
    assert income_tax_minor(5_150_000, R) - income_tax_minor(4_100_000, R) == 385_098


def test_personal_allowance_taper():
    # No taper at/under £100,000; full £12,570 allowance.
    assert personal_allowance_minor(10_000_000, R) == 1_257_000
    # £110,000: £10,000 over → lose £5,000 → PA £7,570.
    assert personal_allowance_minor(11_000_000, R) == 757_000
    # £125,140: exactly £25,140 over → lose £12,570 → PA £0.
    assert personal_allowance_minor(12_514_000, R) == 0


def test_marginal_band_names():
    assert marginal_band_name(1_000_000, R) == "personal_allowance"  # below PA
    assert marginal_band_name(2_000_000, R) == "basic"  # £20,000
    assert marginal_band_name(4_800_000, R) == "higher"  # £48,000
    assert marginal_band_name(11_000_000, R) == "advanced"  # £110,000


def test_rates_for_year_falls_back_with_assumption():
    rates, assumption = rates_for_year("2025-26")
    assert rates is SCOTTISH_2025_26 and assumption is None

    # 2026-27 is deliberately not entered — never guessed. The fallback returns
    # the latest known year AND a visible assumption string (docs/TAX.md §7).
    rates_next, assumption_next = rates_for_year("2026-27")
    assert rates_next is SCOTTISH_2025_26
    assert assumption_next is not None and "2026-27" in assumption_next and "2025-26" in assumption_next
