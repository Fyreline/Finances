"""Pure letting-agent statement parser — app/engines/rent_statement_parser.py,
docs/phases/PHASE-12-rental-automation.md item 1c.

All figures here are SYNTHETIC placeholders (docs/PRIVATE.md redaction scheme) —
they exercise the learned layout's labels, not any real statement's numbers.
"""
from __future__ import annotations

from app.engines.rent_statement_parser import parse_statement_text

# A synthetic statement in the learned letting-agent layout. Placeholder figures:
# rent 1,000.00; commission 9% = 90.00; VAT 20% of that = 18.00; a repairs
# deduction of 50.00; net 842.00 (= 1000 - 90 - 18 - 50). Extra £ amounts on the
# same visual lines (deposit, a metadata figure) mimic the right-hand column
# bleed so the anchored regexes must pick the right one.
_SYNTH = """\
Monthly Rental Statement September 2025
Subject Property: Placeholder Street
Property Reference: TEST REF
Total Rent: £1,000.00
Commission: 9.00 % £90.00 Placeholder Tenant £2,400.00 01/01/25 EPC Ratng: C
VAT: 20.00 % £18.00
Total Costs £158.00
Total Deductons: £158.00
Net Rent sent to you: £842.00 Deposit Amount: £1,200.00
Property Costs Summary for Month
Imported: Repairs & Maintenance (Landlord Direct) -£50.00 Some Contractor £50.00
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
    assert r.repairs_minor == 5_000
    assert r.net_rent_minor == 84_200
    assert r.warnings == []


def test_missing_repairs_is_a_valid_zero_not_a_failure():
    text = "\n".join(line for line in _SYNTH.splitlines() if "Repairs" not in line)
    r = parse_statement_text(text)
    assert r.confident is True  # repairs are optional
    assert r.repairs_minor is None  # None = absent, distinct from a real 0
    assert r.agent_fee_minor == 10_800


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
