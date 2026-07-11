"""Letting-agent monthly-statement parser — pure, no I/O (docs/phases/
PHASE-12-rental-automation.md item 1c).

Takes the *text already extracted* from a confirmed "Monthly Rental Statement"
PDF and returns the structured line items the rental ledger needs — gross rent
received, the agent's commission (+ its VAT, both allowable `agent_fees`), any
landlord-direct repairs/maintenance deduction, and the statement's covered
period. Kept a pure function over a string so it is unit-testable against a
synthetic fixture with placeholder figures, with no real PDF library installed
(mirrors `engines/tax.py` / `engines/insights.py` — engines never do I/O; the
PDF is opened in `app/rent_statement_ingest.py`).

Discipline (same as every money path in this repo):
- **Integer pence everywhere.** A `£` string is parsed to pence exactly once,
  at the boundary here (`_pounds_to_minor`), immediately rounded — the single
  permitted float-touch, same precedent as the Trading 212 `round(x*100)` edge.
- **Best-effort, never a guess** (docs/TAX.md §0 spirit, applied to document
  parsing). A statement is only `confident` when the core line items — covered
  period, gross rent, and the agent commission — are all found against the
  learned layout. A partial read (e.g. rent found, commission line not) reports
  what it found and stays `confident=False`, so the caller leaves it for a human
  in the review queue rather than inventing the missing split.
- **No real figures anywhere in this module or its tests** — the regexes match
  *labels*; the numbers they capture come only from a real document at runtime
  (or a synthetic fixture in tests). docs/PRIVATE.md redaction scheme.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# The learned letting-agent layout is a single-page statement whose summary block
# carries these labelled lines (confirmed by reading the real statements'
# *structure* — labels/layout only, never their figures):
#   "Monthly Rental Statement <Month> <Year>"   -> covered period
#   "Total Rent: £X"                             -> gross rent for the period
#   "Commission: N.NN % £X"                      -> agent commission
#   "VAT: N.NN % £X"                             -> VAT charged on the commission
#   "Repairs & Maintenance (Landlord Direct) -£X"-> a repairs deduction (optional)
#   "Net Rent sent to you: £X"                   -> net remitted (cross-check only)
# extract_text merges the right-hand property-metadata column into some of these
# lines by y-position, so each pattern anchors on its own label and captures the
# FIRST £ amount that immediately follows it — never a later amount bled in from
# an adjacent column.
_MONEY = r"£\s*([\d,]+\.\d{2})"

_PERIOD_RE = re.compile(r"Monthly Rental Statement\s+([A-Za-z]+)\s+(\d{4})", re.IGNORECASE)
_GROSS_RE = re.compile(r"Total Rent\s*:\s*" + _MONEY, re.IGNORECASE)
_COMMISSION_RE = re.compile(r"Commission\s*:\s*[\d.]+\s*%\s*" + _MONEY, re.IGNORECASE)
_VAT_RE = re.compile(r"VAT\s*:\s*[\d.]+\s*%\s*" + _MONEY, re.IGNORECASE)
_REPAIRS_RE = re.compile(
    r"Repairs\s*&\s*Maintenance\s*\(Landlord Direct\)\s*-?\s*" + _MONEY, re.IGNORECASE
)
_NET_RE = re.compile(r"Net Rent sent to you\s*:\s*" + _MONEY, re.IGNORECASE)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass(frozen=True)
class ParsedStatement:
    """Structured amounts extracted from one monthly statement. All money is
    positive integer pence (`kind`/`expense_type` carry the sign semantics in
    the ledger, DATA_MODEL §6). ``None`` means "not found", which is distinct
    from a genuine ``0`` (a statement with no repairs that month)."""

    period_year: int | None = None
    period_month: int | None = None  # 1..12
    period_label: str | None = None  # "September 2025" as printed
    gross_rent_minor: int | None = None
    agent_fee_minor: int | None = None  # commission + VAT (both allowable agent_fees)
    commission_minor: int | None = None
    vat_minor: int | None = None
    repairs_minor: int | None = None  # landlord-direct repairs/maintenance, if present
    net_rent_minor: int | None = None  # cross-check only, not ledgered
    warnings: list[str] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """True only when the covered period, gross rent, and agent commission
        were all found — the minimum for a trustworthy income + agent_fees
        ledger pair. Repairs are genuinely optional (a valid zero), so their
        absence never blocks confidence."""
        return (
            self.period_year is not None
            and self.period_month is not None
            and self.gross_rent_minor is not None
            and self.agent_fee_minor is not None
        )


def _pounds_to_minor(pounds_text: str) -> int:
    """"1,234.56" -> 123456. The one float-touch, rounded immediately to pence
    (docs/ARCHITECTURE.md §6, Trading 212 `round(x*100)` precedent)."""
    return round(float(pounds_text.replace(",", "")) * 100)


def _first(pattern: re.Pattern[str], text: str) -> int | None:
    m = pattern.search(text)
    return _pounds_to_minor(m.group(1)) if m else None


def parse_statement_text(text: str) -> ParsedStatement:
    """Parse a monthly-statement's extracted text into structured pence amounts.
    Never raises; unfound fields are ``None`` and recorded in ``warnings`` so the
    ingest layer can decide confident-vs-review honestly."""
    text = text or ""
    warnings: list[str] = []

    period_year = period_month = None
    period_label = None
    pm = _PERIOD_RE.search(text)
    if pm:
        month_name, year_text = pm.group(1), pm.group(2)
        period_month = _MONTHS.get(month_name.lower())
        if period_month is not None:
            period_year = int(year_text)
            period_label = f"{month_name.title()} {year_text}"
        else:
            warnings.append(f"unrecognised statement month '{month_name}'")
    else:
        warnings.append("statement period line not found")

    gross = _first(_GROSS_RE, text)
    if gross is None:
        warnings.append("gross rent (Total Rent) line not found")

    commission = _first(_COMMISSION_RE, text)
    vat = _first(_VAT_RE, text)
    if commission is None:
        warnings.append("agent commission line not found")
        agent_fee = None
    else:
        # VAT on the management commission is itself an allowable agent cost for
        # a non-VAT-registered landlord (it cannot be reclaimed), so it folds
        # into agent_fees. A missing VAT line is treated as £0 VAT, not a
        # failure — some months carry none.
        agent_fee = commission + (vat or 0)

    repairs = _first(_REPAIRS_RE, text)  # optional — absence is a valid zero, no warning
    net = _first(_NET_RE, text)

    # Soft cross-check (advisory only — the statement has other deduction
    # columns this parser deliberately does not map, so a difference is
    # expected, not an error): captured deductions must not exceed gross minus
    # net, which would mean we over-read an expense and would understate tax.
    if gross is not None and net is not None and agent_fee is not None:
        captured = agent_fee + (repairs or 0)
        if captured > (gross - net) + 100:  # 1.00 tolerance for rounding/pro-rata
            warnings.append("captured deductions exceed gross-minus-net — flagged for review")

    return ParsedStatement(
        period_year=period_year,
        period_month=period_month,
        period_label=period_label,
        gross_rent_minor=gross,
        agent_fee_minor=agent_fee,
        commission_minor=commission,
        vat_minor=vat,
        repairs_minor=repairs,
        net_rent_minor=net,
        warnings=warnings,
    )
