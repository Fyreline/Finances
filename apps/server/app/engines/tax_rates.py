"""Per-year Scottish income-tax rate tables, as DATA — docs/TAX.md §3.

**Adding a tax year = adding a dict, never editing logic** (docs/TAX.md §3,
docs/phases/PHASE-5-tax.md item 2). The band-walking maths in
:func:`income_tax_minor` is year-agnostic; every year-specific number lives
in a :class:`TaxYearRates` value in ``RATES_BY_YEAR``.

Money is integer pence everywhere (docs/ARCHITECTURE.md §6). Tax within a
band is accumulated as ``slice_pence * rate_percent`` (an exact integer) and
divided by 100 once at the end — so for whole-pound incomes (every band edge
and every test figure is a whole pound) the result is exact to the penny with
no float ever touching the money path.

Bands are stored as **taxable-income widths** (income above the personal
allowance), not as total-income thresholds. This is deliberate: it makes the
personal-allowance taper above £100,000 fall out correctly (a tapered PA
simply shrinks the 0% slice; the paid-band widths never move), which a
total-income-threshold table cannot represent without rewriting every edge.
The equivalence to docs/TAX.md §3's total-income table is checked in
``tests/test_tax_rates.py``.

⚠️→✅ **Verification note (Phase 5 implementation, 2026-07-10):** the 2025-26
Scottish bands below were confirmed against the Scottish Government's
2025-26 income-tax policy (Scottish Budget Dec 2024): six bands, starter 19%
through top 48%, higher-rate threshold £43,663, top-rate threshold £125,140,
personal allowance £12,570 (frozen, UK-wide), PA taper £1 per £2 over
£100,000. The Section-24 finance-cost reducer is the **UK** basic rate, 20%,
even for Scottish taxpayers (ITTOIA s274A) — it is NOT a Scottish rate and so
is a module constant here, not a band. **2026-27 is deliberately NOT entered**
(see ``RATES_BY_YEAR``): its figures were not verifiable to the penny at
implementation time, and docs/TAX.md §0's "never guess" rule outranks the
convenience of a current-year number — the engine emits a visible
``assumptions`` line and falls back to 2025-26 instead (docs/TAX.md §7).
"""
from __future__ import annotations

from dataclasses import dataclass

# Section 24 finance-cost tax reducer rate — UK basic rate by statute (ITTOIA
# s274A), applies to Scottish taxpayers too (docs/TAX.md §5a/§5b). Not a
# Scottish band, so it lives here as one constant rather than per-year data.
S24_REDUCER_RATE_PCT = 20

# The property income allowance (docs/TAX.md §5c). Frozen; if HMRC ever moves
# it this becomes per-year data like the bands.
PROPERTY_ALLOWANCE_MINOR = 100_000  # £1,000


@dataclass(frozen=True)
class Band:
    """One tax band, expressed as a width of *taxable* income (pence) and a
    whole-number percentage rate. ``width_minor=None`` means "everything
    above the previous bands" (the top band)."""

    width_minor: int | None
    rate_pct: int
    name: str


@dataclass(frozen=True)
class TaxYearRates:
    tax_year: str
    personal_allowance_minor: int
    pa_taper_threshold_minor: int  # PA reduced £1 per £2 of income above this
    bands: tuple[Band, ...]
    source: str  # citation for the audit trail


# --- 2025-26 Scottish rates (docs/TAX.md §3; verified — see module docstring) ---
# Band widths are (total-income upper − total-income lower) from the §3 table:
#   starter      12,571–15,397  → 15,397 − 12,570 =  2,827
#   basic        15,398–27,491  → 27,491 − 15,397 = 12,094
#   intermediate 27,492–43,662  → 43,662 − 27,491 = 16,171
#   higher       43,663–75,000  → 75,000 − 43,662 = 31,338
#   advanced     75,001–125,140 → 125,140 − 75,000 = 50,140
#   top          over 125,140   → remainder
SCOTTISH_2025_26 = TaxYearRates(
    tax_year="2025-26",
    personal_allowance_minor=1_257_000,  # £12,570
    pa_taper_threshold_minor=10_000_000,  # £100,000
    bands=(
        Band(width_minor=282_700, rate_pct=19, name="starter"),
        Band(width_minor=1_209_400, rate_pct=20, name="basic"),
        Band(width_minor=1_617_100, rate_pct=21, name="intermediate"),
        Band(width_minor=3_133_800, rate_pct=42, name="higher"),
        Band(width_minor=5_014_000, rate_pct=45, name="advanced"),
        Band(width_minor=None, rate_pct=48, name="top"),
    ),
    source="Scottish Budget 2025-26 (Scottish Government income-tax policy, Dec 2024)",
)


# Only years with verified figures live here. A requested year that's absent
# is served the latest available year's rates by :func:`rates_for_year`, which
# also returns the substitution so the engine can surface it as a visible
# `assumptions` line (docs/TAX.md §7 — never a silent copy-forward). 2026-27 is
# intentionally omitted: see the module docstring.
RATES_BY_YEAR: dict[str, TaxYearRates] = {
    "2025-26": SCOTTISH_2025_26,
}

# The newest year we actually hold verified rates for — the fallback when a
# later year is requested but not yet entered.
LATEST_KNOWN_YEAR = "2025-26"


def rates_for_year(tax_year: str) -> tuple[TaxYearRates, str | None]:
    """Rates for ``tax_year``; if that year isn't entered yet, fall back to
    the latest known year and return an assumption string describing the
    substitution (docs/TAX.md §7). Returns ``(rates, assumption_or_None)`` —
    ``assumption`` is ``None`` when the exact year's rates were found."""
    exact = RATES_BY_YEAR.get(tax_year)
    if exact is not None:
        return exact, None
    fallback = RATES_BY_YEAR[LATEST_KNOWN_YEAR]
    assumption = (
        f"{tax_year} Scottish rates not yet entered — using {LATEST_KNOWN_YEAR} rates. "
        "Re-check against the Scottish Budget for the year being filed."
    )
    return fallback, assumption


def personal_allowance_minor(income_minor: int, rates: TaxYearRates) -> int:
    """Personal allowance after the over-£100k taper (£1 lost per £2 of income
    above the taper threshold; fully gone once income reaches PA×2 above it).
    docs/TAX.md §3 "PA tapers from £100k"."""
    if income_minor <= rates.pa_taper_threshold_minor:
        return rates.personal_allowance_minor
    reduction = (income_minor - rates.pa_taper_threshold_minor) // 2
    return max(0, rates.personal_allowance_minor - reduction)


def income_tax_minor(income_minor: int, rates: TaxYearRates) -> int:
    """Total Scottish income tax (pence) on ``income_minor`` of non-savings,
    non-dividend income — the whole of docs/TAX.md §3's band table applied to
    taxable income (income − tapered PA).

    Exact for whole-pound incomes (see module docstring); rounds half-up to the
    nearest penny for any fractional-pound taxable slice."""
    if income_minor <= 0:
        return 0
    taxable = max(0, income_minor - personal_allowance_minor(income_minor, rates))
    remaining = taxable
    hundredths = 0  # Σ slice_pence × rate_pct  (pence × percent); ÷100 → pence
    for band in rates.bands:
        if remaining <= 0:
            break
        width = band.width_minor if band.width_minor is not None else remaining
        slice_minor = min(remaining, width)
        hundredths += slice_minor * band.rate_pct
        remaining -= slice_minor
    return (hundredths + 50) // 100  # round half-up (non-negative)


def marginal_band_name(income_minor: int, rates: TaxYearRates) -> str:
    """The band in which the topmost taxable pound of ``income_minor`` falls —
    i.e. the rate the next pound of income (e.g. rental profit stacked on
    employment) is taxed at (docs/TAX.md §3.3 "marginal rate")."""
    taxable = max(0, income_minor - personal_allowance_minor(income_minor, rates))
    if taxable <= 0:
        return "personal_allowance"
    consumed = 0
    last = rates.bands[0].name
    for band in rates.bands:
        last = band.name
        width = band.width_minor if band.width_minor is not None else taxable - consumed
        consumed += width
        if taxable <= consumed:
            return band.name
    return last
