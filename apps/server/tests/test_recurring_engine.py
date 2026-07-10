"""app/engines/recurring.py — cadence detection, docs/DATA_MODEL.md §3a.

Fixture months cover the docs/phases/PHASE-4-insights.md item 3 list: a stable
£9.99 sub, a price-rise sub, a weekly gym, an annual insurance, Tesco noise
(must NOT cluster), a tolerated late payment, and salary detection on incoming.
All figures are synthetic placeholders (docs/PRIVATE.md redaction scheme).
"""
from __future__ import annotations

from app.engines.recurring import (
    TxnLike,
    cadence_for_gaps,
    cluster_by_amount,
    detect_recurring,
    merchant_key,
    monthly_equivalent_minor,
)

AS_OF = "2026-07-15"


def _tx(local_date: str, amount_minor: int, counterparty: str, category_key: str | None = None) -> TxnLike:
    return TxnLike(local_date=local_date, amount_minor=amount_minor, counterparty=counterparty, category_key=category_key)


# ------------------------------------------------------------- merchant_key
def test_merchant_key_strips_branch_numbers():
    assert merchant_key("TESCO STORES 3412") == "tesco stores"
    assert merchant_key("NETFLIX.COM") == "netflix com"
    assert merchant_key("Sainsbury's S/Mkt 099") == "sainsbury s s mkt"


def test_merchant_key_blank_for_missing_counterparty():
    assert merchant_key(None) == ""
    assert merchant_key("  ") == ""


# --------------------------------------------------------------- cadence
def test_cadence_windows():
    assert cadence_for_gaps([30, 31, 30]) == "monthly"
    assert cadence_for_gaps([7, 7, 6]) == "weekly"
    assert cadence_for_gaps([91, 90, 92]) == "quarterly"
    assert cadence_for_gaps([365, 366]) == "annual"


def test_cadence_rejects_gap_over_1_6x_median():
    # median 30, one gap of 60 (2×) → rejected (a fully missed month)
    assert cadence_for_gaps([30, 60, 30]) is None


def test_cadence_tolerates_a_late_but_not_missed_payment():
    # median 30.5, longest gap 47 ≤ 1.6×30.5 = 48.8 → still monthly (one late beat)
    assert cadence_for_gaps([30, 31, 47, 30]) == "monthly"


# --------------------------------------------------------------- clustering
def test_tesco_noise_does_not_cluster():
    """Variable grocery amounts at one merchant never form a ≥3 same-amount
    cluster, so Tesco is never detected as recurring (docs/DATA_MODEL.md
    §3a.1)."""
    txns = [
        _tx("2026-05-03", -4212, "TESCO STORES 3412", "groceries"),
        _tx("2026-05-19", -8770, "TESCO STORES 3412", "groceries"),
        _tx("2026-06-02", -2199, "TESCO STORES 3412", "groceries"),
        _tx("2026-06-21", -11450, "TESCO STORES 3412", "groceries"),
        _tx("2026-07-05", -6301, "TESCO STORES 3412", "groceries"),
    ]
    detected = detect_recurring(txns, as_of=AS_OF)
    assert detected == []


def test_fixed_amount_clusters_variable_does_not():
    txns = [_tx("2026-01-01", -999, "x"), _tx("2026-02-01", -999, "x"), _tx("2026-03-01", -12000, "x")]
    clusters = cluster_by_amount(txns)
    assert any(len(c) == 2 for c in clusters)  # the two £9.99 rows cluster
    assert any(len(c) == 1 for c in clusters)  # the £120 outlier stands alone


# ----------------------------------------------------- the £9.99 subscription
def test_stable_monthly_sub_detected_high_confidence():
    txns = [
        _tx("2026-02-14", -999, "NETFLIX.COM", "subscriptions"),
        _tx("2026-03-14", -999, "NETFLIX.COM", "subscriptions"),
        _tx("2026-04-14", -999, "NETFLIX.COM", "subscriptions"),
        _tx("2026-05-14", -999, "NETFLIX.COM", "subscriptions"),
        _tx("2026-06-14", -999, "NETFLIX.COM", "subscriptions"),
    ]
    detected = detect_recurring(txns, as_of=AS_OF)
    assert len(detected) == 1
    sub = detected[0]
    assert sub.cadence == "monthly"
    assert sub.typical_amount_minor == -999
    assert sub.occurrences == 5
    assert sub.confidence >= 0.8
    assert sub.merchant_key == "netflix com"


# ------------------------------------------------------------ price-rise sub
def test_price_rise_surfaces_old_and_new():
    # A £1.50 rise (£9.99 → £11.49) stays inside the ±£1.50 clustering floor,
    # so it forms ONE cluster and the drift surfaces. (A larger jump would
    # exceed the ±12%/±£1.50 tolerance and split into two clusters — a
    # documented limit of the DATA_MODEL §3a.1 algorithm, not a bug.)
    txns = [
        _tx("2026-02-10", -999, "Spotify", "subscriptions"),
        _tx("2026-03-10", -999, "Spotify", "subscriptions"),
        _tx("2026-04-10", -999, "Spotify", "subscriptions"),
        _tx("2026-05-10", -1149, "Spotify", "subscriptions"),
        _tx("2026-06-10", -1149, "Spotify", "subscriptions"),
    ]
    detected = detect_recurring(txns, as_of=AS_OF)
    assert len(detected) == 1
    sub = detected[0]
    assert sub.cadence == "monthly"
    # drift = (1149 - 999) / 999 * 100 ≈ 15.0% → ≥10% (price_rise tip threshold)
    assert sub.amount_drift_pct >= 10.0
    assert sub.earliest_amount_minor == -999
    assert sub.latest_amount_minor == -1149


# --------------------------------------------------------------- weekly gym
def test_weekly_gym_detected():
    txns = [_tx(f"2026-06-0{d}" if d < 10 else f"2026-06-{d}", -650, "PureGym") for d in (1, 8, 15, 22, 29)]
    detected = detect_recurring(txns, as_of=AS_OF)
    assert len(detected) == 1
    assert detected[0].cadence == "weekly"
    assert monthly_equivalent_minor(detected[0].typical_amount_minor, "weekly") == round(-650 * 52 / 12)


# ----------------------------------------------------------- annual insurance
def test_annual_insurance_detected():
    txns = [
        _tx("2024-07-01", -18000, "Aviva Insurance"),
        _tx("2025-07-05", -18500, "Aviva Insurance"),
        _tx("2026-07-02", -19000, "Aviva Insurance"),
    ]
    detected = detect_recurring(txns, as_of="2026-07-15")
    assert len(detected) == 1
    assert detected[0].cadence == "annual"


# ---------------------------------------------------- cancel-candidate flag
def test_cancel_candidate_flagged_for_quiet_small_sub():
    # subscriptions, ≥4 months tenure, ≤£25, no non-recurring txns in 90 days
    txns = [
        _tx("2026-02-14", -799, "OldApp", "subscriptions"),
        _tx("2026-03-14", -799, "OldApp", "subscriptions"),
        _tx("2026-04-14", -799, "OldApp", "subscriptions"),
        _tx("2026-05-14", -799, "OldApp", "subscriptions"),
        _tx("2026-06-14", -799, "OldApp", "subscriptions"),
    ]
    detected = detect_recurring(txns, as_of=AS_OF)
    assert detected[0].cancel_candidate is True


def test_cancel_candidate_not_flagged_when_merchant_has_recent_extra_spend():
    txns = [
        _tx("2026-02-14", -799, "OldApp", "subscriptions"),
        _tx("2026-03-14", -799, "OldApp", "subscriptions"),
        _tx("2026-04-14", -799, "OldApp", "subscriptions"),
        _tx("2026-05-14", -799, "OldApp", "subscriptions"),
        _tx("2026-06-14", -799, "OldApp", "subscriptions"),
        _tx("2026-07-01", -2500, "OldApp", "subscriptions"),  # a recent one-off → active use
    ]
    detected = detect_recurring(txns, as_of=AS_OF)
    sub = next(d for d in detected if d.cadence == "monthly")
    assert sub.cancel_candidate is False


# ------------------------------------------------------------- income anchor
def test_salary_detected_on_incoming():
    txns = [
        _tx("2026-04-28", 250000, "ACME PAYROLL"),
        _tx("2026-05-28", 250000, "ACME PAYROLL"),
        _tx("2026-06-28", 250000, "ACME PAYROLL"),
    ]
    detected = detect_recurring(txns, as_of=AS_OF, direction="in")
    assert len(detected) == 1
    assert detected[0].cadence == "monthly"
    assert detected[0].typical_amount_minor == 250000  # positive (incoming)
