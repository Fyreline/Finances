"""Pure letting-agent statement parser — app/engines/rent_statement_parser.py,
docs/phases/PHASE-12-rental-automation.md item 1c, extended docs/phases/
PHASE-13-rental-history-and-safe-to-spend-fix.md item C (itemised Property
Costs Summary deductions).

All figures here are SYNTHETIC placeholders (docs/PRIVATE.md redaction scheme) —
they exercise the learned layout's labels, not any real statement's numbers.
"""
from __future__ import annotations

from app.engines.rent_statement_parser import ParsedCost, parse_statement_text

# A synthetic statement in the learned letting-agent layout. Placeholder figures:
# rent 1,000.00; commission 9% = 90.00; VAT 20% of that = 18.00; one itemised
# property cost of 50.00 ("Total Costs" is the costs-section's own sum, not the
# whole deduction); total deductions 158.00 (90+18+50); net 842.00 (1000-158).
# Extra £ amounts on the same visual lines (deposit, a metadata figure) mimic
# the right-hand column bleed so the anchored regexes must pick the right one.
_SYNTH = """\
Monthly Rental Statement September 2025
Subject Property: Placeholder Street
Property Reference: TEST REF
Total Rent: £1,000.00
Commission: 9.00 % £90.00 Placeholder Tenant £2,400.00 01/01/25 EPC Ratng: C
VAT: 20.00 % £18.00
Total Costs £50.00
Total Deductons: £158.00
Net Rent sent to you: £842.00 Deposit Amount: £1,200.00
Property Costs Summary for Month
Placeholder Council - General Maintenance £50.00
Property Factor No
"""


def test_parses_all_core_line_items():
    r = parse_statement_text(_SYNTH)
    assert r.confident is True
    assert (r.period_year, r.period_month) == (2025, 9)
    assert r.period_label == "September 2025"
    assert r.gross_rent_minor == 100_000
    assert r.commission_minor == 9_000
    assert r.vat_minor == 1_800
    assert r.agent_fee_minor == 10_800  # commission + VAT, one allowable agent_fees figure
    assert r.total_costs_minor == 5_000
    assert r.total_deductions_minor == 15_800
    assert r.net_rent_minor == 84_200
    assert r.repairs_minor is None  # no legacy single-line repairs label here
    assert r.warnings == []


def test_property_costs_summary_single_line_parsed_and_reconciled():
    r = parse_statement_text(_SYNTH)
    assert r.property_costs == [ParsedCost("Placeholder Council - General Maintenance", 5_000)]
    assert r.property_costs_total_minor == 5_000
    assert r.property_costs_reconciled is True
    assert r.repairs_rows() == [ParsedCost("Placeholder Council - General Maintenance", 5_000)]


def test_property_costs_summary_multiple_lines_all_captured():
    text = _SYNTH.replace("Total Costs £50.00", "Total Costs £90.00").replace(
        "Placeholder Council - General Maintenance £50.00",
        "Placeholder Council - General Maintenance £50.00\n"
        "Some Contractor - Boiler Service £40.00",
    )
    r = parse_statement_text(text)
    assert len(r.property_costs) == 2
    assert r.property_costs[0] == ParsedCost("Placeholder Council - General Maintenance", 5_000)
    assert r.property_costs[1] == ParsedCost("Some Contractor - Boiler Service", 4_000)
    assert r.property_costs_total_minor == 9_000
    assert r.property_costs_reconciled is True
    assert len(r.repairs_rows()) == 2


def test_property_costs_summary_present_but_empty_is_a_valid_zero():
    # Section header with no cost lines under it (a genuine no-deductions month)
    # — never a failure, never a guessed amount.
    text = _SYNTH.replace("Placeholder Council - General Maintenance £50.00\n", "").replace(
        "Total Costs £50.00", "Total Costs £0.00"
    )
    r = parse_statement_text(text)
    assert r.confident is True
    assert r.property_costs == []
    assert r.property_costs_reconciled is True
    assert r.repairs_rows() == []
    assert not any("reconcile" in w.lower() for w in r.warnings)


def test_property_costs_reconciliation_mismatch_leaves_costs_unledgered():
    # Total Costs disagrees with the itemised line's own amount by more than the
    # rounding tolerance — a signal the section wasn't read cleanly. Never guess
    # which figure is right: repairs_rows() must emit nothing (docs/TAX.md §0).
    text = _SYNTH.replace("Total Costs £50.00", "Total Costs £999.00")
    r = parse_statement_text(text)
    assert r.confident is True  # core line items are still fine
    assert r.property_costs_reconciled is False
    assert r.repairs_rows() == []
    assert any("reconcile" in w.lower() for w in r.warnings)


def test_legacy_repairs_line_used_as_fallback_when_no_costs_section():
    # Older-style statement: a single explicit landlord-direct repairs line,
    # no "Property Costs Summary for Month" section at all.
    text = (
        "Monthly Rental Statement September 2025\n"
        "Total Rent: £1,000.00\n"
        "Commission: 9.00 % £90.00\n"
        "VAT: 20.00 % £18.00\n"
        "Repairs & Maintenance (Landlord Direct) -£50.00\n"
        "Net Rent sent to you: £842.00\n"
    )
    r = parse_statement_text(text)
    assert r.confident is True
    assert r.property_costs == []
    assert r.repairs_minor == 5_000
    assert r.repairs_rows() == [ParsedCost("Landlord-direct repairs & maintenance", 5_000)]


def test_missing_commission_is_not_confident():
    text = "\n".join(line for line in _SYNTH.splitlines() if not line.startswith("Commission"))
    r = parse_statement_text(text)
    assert r.confident is False
    assert r.gross_rent_minor == 100_000  # what it DID find is still reported
    assert r.agent_fee_minor is None
    assert any("commission" in w.lower() for w in r.warnings)


def test_missing_period_is_not_confident():
    text = "\n".join(line for line in _SYNTH.splitlines() if "Monthly Rental Statement" not in line)
    r = parse_statement_text(text)
    assert r.confident is False
    assert r.period_month is None
    assert any("period" in w.lower() for w in r.warnings)


def test_vat_absent_folds_to_zero_not_failure():
    text = "\n".join(line for line in _SYNTH.splitlines() if not line.startswith("VAT"))
    r = parse_statement_text(text)
    assert r.confident is True
    assert r.vat_minor is None
    assert r.agent_fee_minor == 9_000  # commission only


def test_over_captured_deductions_are_flagged():
    # net says 990 (only 10 deducted) but we'd capture 90+18+50=158 > gross-net(10)
    text = _SYNTH.replace("Net Rent sent to you: £842.00", "Net Rent sent to you: £990.00")
    r = parse_statement_text(text)
    assert any("exceed" in w.lower() for w in r.warnings)


def test_empty_text_is_safe():
    r = parse_statement_text("")
    assert r.confident is False
    assert r.gross_rent_minor is None
    assert r.property_costs == []
    assert r.repairs_rows() == []
