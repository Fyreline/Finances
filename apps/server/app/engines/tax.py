"""The Self Assessment rental-tax estimator — docs/TAX.md §5, pure functions.

**Two load-bearing rules from docs/TAX.md §0, enforced here in code:**

1. **The estimator never guesses.** :func:`missing_inputs` returns the list of
   required-but-unset config fields; while it is non-empty the caller returns
   ``estimate: null`` and shows "estimate needs N inputs" — never a number
   built on an invented mortgage-interest / employment / rental figure. A
   wrong-but-confident tax number is the worst output this app could produce.
2. **The disclaimer is load-bearing.** :data:`DISCLAIMER` is attached to every
   estimate this module produces; the router echoes it in every tax response
   and the UI renders it on every tax surface (docs/DESIGN.md §4g).

Everything here is a pure function over plain ints + a
:class:`~app.engines.tax_rates.TaxYearRates` — no DB, no I/O (the router in
``routers/tax.py`` reads ``rental_ledger`` rows + ``tax_config`` and calls
these). Money is integer pence throughout (docs/ARCHITECTURE.md §6).

Both routes of docs/TAX.md §5 are always computed and both returned in
``comparison``; ``method_used`` is the cheaper one. The three §5d worked
examples are pinned, hand-computed, in ``tests/test_tax_engine.py`` — those
tests are the audit trail (docs/TAX.md §7, docs/phases/PHASE-5-tax.md item 3).
"""
from __future__ import annotations

from dataclasses import dataclass

from .tax_rates import (
    PROPERTY_ALLOWANCE_MINOR,
    S24_REDUCER_RATE_PCT,
    TaxYearRates,
    income_tax_minor,
    marginal_band_name,
    personal_allowance_minor,
)

# docs/TAX.md §0 / docs/DESIGN.md §4g. Present in every estimate response and
# rendered (non-dismissable) on every tax UI surface.
DISCLAIMER = (
    "Kakeibo estimates for planning only — it is not tax advice, not an accountant, "
    "and not a substitute for HMRC's own calculators. Every figure must be checked "
    "against HMRC or an accountant before it goes on a real Self Assessment return."
)

# National Insurance on ordinary residential letting is £0 (docs/TAX.md §3
# "National Insurance"): letting a single property is investment income, not a
# trade, so no Class 4; and Class 2 was effectively abolished for the
# self-employed from April 2024. The engine states this explicitly rather than
# omitting the line in a way that could look like an oversight.
NIC_NOTE = (
    "£0 — ordinary residential letting is not a trade, so its profits carry no "
    "Class 4 NIC, and Class 2 no longer applies (abolished for the self-employed "
    "from April 2024). Employment NI is handled by PAYE and is out of scope here."
)

METHOD_EXPENSES = "expenses_plus_s24"
METHOD_ALLOWANCE = "property_allowance"

# The ✅ allowable expense types (docs/TAX.md §4). `ground_rent_service` is
# config-gated (leasehold only) and handled separately by the caller;
# `mortgage_interest` feeds S24 only and is excluded from expense totals;
# `capital_improvement` is tracked for CGT but allowable nowhere.
ALLOWABLE_EXPENSE_TYPES = frozenset(
    {"agent_fees", "insurance", "repairs", "other_allowable", "ground_rent_service"}
)
EXCLUDED_FROM_EXPENSES = frozenset({"mortgage_interest", "capital_improvement"})


def _round_pct(base_minor: int, rate_pct: int) -> int:
    """``base × rate%`` in integer pence, round half-up. Exact for whole-pound
    bases (every test figure)."""
    return (base_minor * rate_pct + 50) // 100


# --------------------------------------------------------------------------- #
#  Missing-input gating (docs/TAX.md §0 rule 2, §7 acceptance)                 #
# --------------------------------------------------------------------------- #
def missing_inputs(
    *,
    has_mortgage: int | None,
    annual_mortgage_interest_minor: int | None,
    employment_gross_annual_minor: int | None,
    ledger_finance_costs_minor: int = 0,
) -> list[str]:
    """The required-but-unset inputs, in the order the UI should list them
    (docs/TAX.md §7). While this is non-empty the caller returns
    ``estimate: null`` — no guessed numbers, ever.

    - ``has_mortgage`` is always required (NULL = the open HANDOFF Q1).
    - the mortgage-interest figure is required *only if* there is a mortgage,
      and is satisfied by **either** the config certificate figure **or**
      actual ``mortgage_interest`` ledger rows (docs/TAX.md §5a says the ledger
      is the source; HANDOFF Q1 says the certificate figure "unblocks
      estimates immediately" — either path counts, neither is invented).
    - ``employment_gross_annual`` is always required — it places the rental
      profit in the correct Scottish band; guessing it "misstates the estimate
      by half" (docs/TAX.md §2).
    """
    missing: list[str] = []
    if has_mortgage is None:
        missing.append("has_mortgage")
    elif has_mortgage == 1 and annual_mortgage_interest_minor is None and ledger_finance_costs_minor == 0:
        missing.append("annual_mortgage_interest")
    if employment_gross_annual_minor is None:
        missing.append("employment_gross_annual")
    return missing


# --------------------------------------------------------------------------- #
#  Loss carry-forward (docs/TAX.md §4 "Losses") — derived, never stored        #
# --------------------------------------------------------------------------- #
def loss_brought_forward_minor(prior_years: list[tuple[int, int]]) -> int:
    """Property-business loss carried into the year after ``prior_years``.

    ``prior_years`` is chronological ``(gross_rents_minor, allowable_minor)``
    pairs. A property loss carries forward automatically against future
    property profits (docs/TAX.md §4); nothing is persisted — the caller
    recomputes this from ledger rows each time. A loss uses the actual-expenses
    figures (losses arise from real expenses, not the £1,000 allowance)."""
    carried = 0
    for gross_minor, allowable_minor in prior_years:
        net = (gross_minor - allowable_minor) - carried
        carried = -net if net < 0 else 0
    return carried


# --------------------------------------------------------------------------- #
#  Payments on account (docs/TAX.md §6)                                        #
# --------------------------------------------------------------------------- #
def payments_on_account(
    *, sa_tax_due_minor: int, tax_at_source_minor: int, tax_year: str
) -> dict:
    """The 80%-collected-at-source POA test, computed properly rather than
    assumed (docs/TAX.md §6). POAs are required when the SA balancing bill
    exceeds £1,000 **and** less than 80% of the year's total tax was collected
    at source (PAYE). Each POA is 50% of this year's SA bill, due 31 Jan and
    31 Jul following the tax year."""
    threshold_minor = 100_000  # £1,000
    total_tax_minor = sa_tax_due_minor + tax_at_source_minor
    pct_at_source = (tax_at_source_minor / total_tax_minor) if total_tax_minor > 0 else 1.0
    required = sa_tax_due_minor > threshold_minor and pct_at_source < 0.80

    start_year = int(tax_year.split("-")[0])
    jan = f"{start_year + 2}-01-31"
    jul = f"{start_year + 2}-07-31"

    if not required:
        return {
            "required": False,
            "reason": (
                "not required — "
                + (
                    "SA bill is £1,000 or less"
                    if sa_tax_due_minor <= threshold_minor
                    else "80% or more of total tax is already collected at source (PAYE)"
                )
            ),
            "pct_collected_at_source": round(pct_at_source, 4),
            "amounts_minor": [],
            "dates": [],
        }

    first = sa_tax_due_minor // 2
    second = sa_tax_due_minor - first  # the two halves sum exactly to the bill
    return {
        "required": True,
        "reason": "SA bill exceeds £1,000 and under 80% of total tax is collected at source (PAYE)",
        "pct_collected_at_source": round(pct_at_source, 4),
        "amounts_minor": [first, second],
        "dates": [jan, jul],
    }


# --------------------------------------------------------------------------- #
#  The estimate itself (docs/TAX.md §5)                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EstimateInputs:
    gross_rents_minor: int
    allowable_expenses_minor: int  # Σ ✅ expense rows; mortgage_interest & capital already EXCLUDED
    finance_costs_minor: int  # mortgage interest — S24 only, never an expense deduction
    employment_income_minor: int
    tax_year: str
    loss_brought_forward_minor: int = 0
    tax_at_source_minor: int | None = None  # PAYE income tax; defaults to income_tax(employment)


def estimate_tax(inp: EstimateInputs, rates: TaxYearRates, *, assumptions: list[str] | None = None) -> dict:
    """Compute both routes of docs/TAX.md §5 and report the cheaper one.

    Assumes all required inputs are present — the caller must have already
    consulted :func:`missing_inputs` and returned ``null`` if any were unset.
    """
    assumptions = list(assumptions or [])
    emp = inp.employment_income_minor
    tax_on_emp = income_tax_minor(emp, rates)

    # -- Route 1: actual expenses + Section 24 credit (docs/TAX.md §5a) --------
    #   profit        = max(0, gross − allowable − loss_b/f)
    #   tax_on_profit = tax(emp + profit) − tax(emp)   [marginal stacking — exact across bands]
    #   s24_credit    = 20% × min(finance_costs, profit, adjusted_income_above_PA)
    #   tax_due       = max(0, tax_on_profit − s24_credit)   [excess credit carries forward]
    profit1 = max(0, inp.gross_rents_minor - inp.allowable_expenses_minor - inp.loss_brought_forward_minor)
    tax_on_profit1 = income_tax_minor(emp + profit1, rates) - tax_on_emp

    total_income1 = emp + profit1
    adjusted_income_above_pa = max(0, total_income1 - personal_allowance_minor(total_income1, rates))
    s24_base = min(inp.finance_costs_minor, profit1, adjusted_income_above_pa)
    s24_credit = _round_pct(s24_base, S24_REDUCER_RATE_PCT)
    tax_due1 = max(0, tax_on_profit1 - s24_credit)
    # Unused finance costs / unused credit carry forward (docs/TAX.md §5a) —
    # reported for the audit trail, not applied automatically in v1.
    s24_credit_unused = max(0, s24_credit - tax_on_profit1)
    finance_costs_unused = max(0, inp.finance_costs_minor - s24_base)

    # -- Route 2: the £1,000 property allowance (docs/TAX.md §5c) --------------
    #   gross ≤ £1,000 → full relief, no tax, no reporting.
    #   else → profit = gross − £1,000; NO expenses; NO s24 credit (conservative,
    #          docs/TAX.md §5c ⚠️ — can only overstate route 2, never understate).
    if inp.gross_rents_minor <= PROPERTY_ALLOWANCE_MINOR:
        profit2 = 0
        allowance_used = inp.gross_rents_minor
    else:
        profit2 = inp.gross_rents_minor - PROPERTY_ALLOWANCE_MINOR
        allowance_used = PROPERTY_ALLOWANCE_MINOR
    tax_on_profit2 = income_tax_minor(emp + profit2, rates) - tax_on_emp
    tax_due2 = tax_on_profit2  # no credit combinable with the allowance

    # -- Choose the cheaper route (ties → expenses route, the usual winner) ----
    if tax_due1 <= tax_due2:
        method_used = METHOD_EXPENSES
        tax_due = tax_due1
        chosen_s24 = s24_credit
        chosen_profit = profit1
    else:
        method_used = METHOD_ALLOWANCE
        tax_due = tax_due2
        chosen_s24 = 0
        chosen_profit = profit2

    tax_at_source = inp.tax_at_source_minor if inp.tax_at_source_minor is not None else tax_on_emp
    poa = payments_on_account(
        sa_tax_due_minor=tax_due, tax_at_source_minor=tax_at_source, tax_year=inp.tax_year
    )

    return {
        "method_used": method_used,
        "tax_due_minor": tax_due,
        "s24_credit_minor": chosen_s24,
        "profit_minor": chosen_profit,
        "marginal_band": marginal_band_name(emp + profit1, rates),
        "nic_due_minor": 0,
        "nic_note": NIC_NOTE,
        "loss_brought_forward_minor": inp.loss_brought_forward_minor,
        "payments_on_account": poa,
        "comparison": {
            METHOD_EXPENSES: {
                "gross_rents_minor": inp.gross_rents_minor,
                "allowable_expenses_minor": inp.allowable_expenses_minor,
                "loss_brought_forward_minor": inp.loss_brought_forward_minor,
                "profit_minor": profit1,
                "tax_on_profit_minor": tax_on_profit1,
                "finance_costs_minor": inp.finance_costs_minor,
                "s24_base_minor": s24_base,
                "s24_credit_minor": s24_credit,
                "s24_credit_unused_minor": s24_credit_unused,
                "finance_costs_unused_minor": finance_costs_unused,
                "tax_due_minor": tax_due1,
            },
            METHOD_ALLOWANCE: {
                "gross_rents_minor": inp.gross_rents_minor,
                "allowance_minor": allowance_used,
                "profit_minor": profit2,
                "tax_on_profit_minor": tax_on_profit2,
                "s24_credit_minor": 0,
                "tax_due_minor": tax_due2,
            },
        },
        "assumptions": assumptions,
        "disclaimer": DISCLAIMER,
    }
