"""app/engines/recurring.py — cadence detection, docs/DATA_MODEL.md §3a.

Fixture months cover the docs/phases/PHASE-4-insights.md item 3 list: a stable
£9.99 sub, a price-rise sub, a weekly gym, an annual insurance, Tesco noise
(must NOT cluster), a tolerated late payment, and salary detection on incoming.
All figures are synthetic placeholders (docs/PRIVATE.md redaction scheme).
"""
from __future__ import annotations

from datetime import date, timedelta

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


# ------------------------------------------- Phase 13 item D: cadence robustness
def test_cadence_monthly_window_admits_five_week_gaps():
    """A weekday-anchored payday alternates 28/35-day calendar gaps; a run of
    35s (5-week beats) is still monthly under the widened 27–36 window
    (docs/phases/PHASE-13 item D.1)."""
    assert cadence_for_gaps([35, 35, 35]) == "monthly"
    assert cadence_for_gaps([28, 35, 28, 35]) == "monthly"
    assert cadence_for_gaps([27, 28, 27]) == "monthly"


def test_cadence_tolerates_a_bounded_holiday_outlier_in_a_long_cluster():
    """One holiday-shifted long gap no longer vetoes an otherwise-consistent
    monthly cluster, PROVIDED the cluster is long enough that one outlier is a
    small fraction (len//8) of its gaps (docs/phases/PHASE-13 item D.2)."""
    # 21 gaps of 28 + one 90-day Christmas gap → allowance 22//8 = 2, one
    # outlier ≤ allowance → still monthly (median of the kept 28s).
    assert cadence_for_gaps([28] * 21 + [90]) == "monthly"


def test_cadence_still_rejects_too_many_outliers_short_cluster_unchanged():
    """The safety net is narrowed, not removed: a short cluster tolerates NO
    outlier (a single missed month in a 3-gap cluster is still rejected,
    exactly as before), and a longer cluster with more outliers than its
    allowance is still rejected as genuinely irregular."""
    assert cadence_for_gaps([30, 60, 30]) is None  # 3 gaps, allowance 0, unchanged
    # 9 gaps, allowance 9//8 = 1, but two 90-day outliers → rejected.
    assert cadence_for_gaps([28, 28, 28, 90, 28, 28, 90, 28, 28]) is None


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


def test_income_anchor_carries_observed_gaps():
    """Phase 11: a detected anchor exposes its real calendar-day gaps so the
    current payday period can be derived from history, not a day-of-month
    rule. Last-Fridays here are 28/28 days apart."""
    txns = [
        _tx("2026-05-29", 210000, "ACME PAYROLL"),
        _tx("2026-06-26", 210000, "ACME PAYROLL"),
        _tx("2026-07-31", 210000, "ACME PAYROLL"),
    ]
    detected = detect_recurring(txns, as_of=AS_OF, direction="in")
    assert detected[0].gaps_days == [28, 35]  # 29 May→26 Jun, 26 Jun→31 Jul


# --------------------------------- Phase 13 item D: the real safe-to-spend bug
def _last_friday(year: int, month: int) -> date:
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != 4:  # 4 == Friday
        d -= timedelta(days=1)
    return d


def test_last_friday_payday_with_holiday_gap_is_detected_monthly():
    """The exact real shape from docs/phases/PHASE-13 item D, with SYNTHETIC
    dates/amount: a 'last Friday of the month' salary over ~2.5 years, whose
    calendar gaps alternate 28/35 days, plus one Christmas run paid early in
    December followed by a long gap into late February (a short-then-long
    outlier pair). The pre-Phase-13 outlier rule vetoed the whole 30-strong
    cluster on that one long gap and returned NOTHING — the direct cause of
    safe-to-spend never auto-detecting the user's income. It must now be found
    as a single monthly anchor."""
    months: list[tuple[int, int]] = []
    y, m = 2023, 11
    while (y, m) <= (2026, 6):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    dates: list[date] = []
    for yy, mm in months:
        if (yy, mm) == (2024, 12):
            dates.append(date(2024, 12, 6))  # paid early before Christmas
            continue
        if (yy, mm) == (2025, 1):
            continue  # January run skipped → long gap out to late February
        dates.append(_last_friday(yy, mm))

    txns = [_tx(d.isoformat(), 250000, "ACME PAYROLL") for d in dates]
    detected = detect_recurring(txns, as_of=AS_OF, direction="in")
    salary = [d for d in detected if d.typical_amount_minor == 250000]
    assert len(salary) == 1
    assert salary[0].cadence == "monthly"
    assert salary[0].occurrences >= 25  # the whole cluster survives, not zero
    assert salary[0].confidence >= 0.35  # clears the income-anchor floor


# ---------------------- Phase 14 item 1b: earliest-amount-outlier tolerance
def test_earliest_outlier_folds_into_a_tight_following_run():
    """A new job's prorated first paycheck (a lone leading amount-outlier)
    followed by a tight steady-state run should, with the recency-sensitive
    tolerance on, form ONE cluster of all three rather than a dropped singleton
    plus a 2-occurrence cluster that never reaches ≥3 (docs/phases/PHASE-14
    item 1b). SYNTHETIC amounts — a partial first month, then steady."""
    txns = [
        _tx("2026-04-24", 120_000, "NEW EMPLOYER"),  # prorated first paycheck
        _tx("2026-05-29", 250_000, "NEW EMPLOYER"),  # steady-state
        _tx("2026-06-26", 250_000, "NEW EMPLOYER"),
    ]
    # Default (outgoing/general) clustering splits it: singleton + a pair.
    plain = cluster_by_amount(txns)
    assert sorted(len(c) for c in plain) == [1, 2]
    # Recency-sensitive clustering folds the leading outlier into the run.
    folded = cluster_by_amount(txns, tolerate_earliest_outlier=True)
    assert len(folded) == 1 and len(folded[0]) == 3

    detected = detect_recurring(txns, as_of=AS_OF, direction="in", tolerate_earliest_outlier=True)
    assert len(detected) == 1
    anchor = detected[0]
    assert anchor.cadence == "monthly"
    assert anchor.occurrences == 3
    assert anchor.typical_amount_minor == 250_000  # median, not dragged by the outlier
    assert anchor.confidence >= 0.35  # clears the income-anchor floor


def test_earliest_outlier_tolerance_does_not_resurrect_a_two_payment_job():
    """Even with the tolerance, a genuinely 2-payment-old job (one prorated,
    one steady) has only ONE tight occurrence after the outlier, so it stays
    below ≥3 and is honestly not detected (docs/phases/PHASE-14 item 1b)."""
    txns = [
        _tx("2026-05-29", 120_000, "NEW EMPLOYER"),
        _tx("2026-06-26", 250_000, "NEW EMPLOYER"),
    ]
    folded = cluster_by_amount(txns, tolerate_earliest_outlier=True)
    assert max(len(c) for c in folded) < 3  # nothing to fold into (run of 1)
    assert detect_recurring(txns, as_of=AS_OF, direction="in", tolerate_earliest_outlier=True) == []


def test_earliest_outlier_tolerance_is_off_by_default_for_outgoings():
    """The tolerance must never loosen the general outgoing/subscription path:
    a variable-then-fixed shape at a merchant still splits (docs/phases/PHASE-14
    item 1b scope note)."""
    txns = [_tx("2026-04-01", -1500, "x"), _tx("2026-05-01", -999, "x"), _tx("2026-06-01", -999, "x")]
    clusters = cluster_by_amount(txns)  # default: no folding
    assert sorted(len(c) for c in clusters) == [1, 2]


def test_eight_outgoing_committed_costs_unaffected_by_the_fix():
    """Regression guard (docs/phases/PHASE-13 item D.3): loosening the cadence/
    outlier logic must NOT stop the already-working outgoing committed-cost
    detections. Eight distinct synthetic outgoing patterns — the shape, not the
    real user's values — must all still detect at their expected cadence, and
    nothing spurious appear."""

    def monthly(merchant: str, amount: int, day: int, cat: str) -> list[TxnLike]:
        return [_tx(f"2026-{mm:02d}-{day:02d}", amount, merchant, cat) for mm in (2, 3, 4, 5, 6)]

    txns: list[TxnLike] = []
    # Six clean monthly committed costs (fixed + subscriptions/fun).
    txns += monthly("FLAT SHARE TRANSFER", -16000, 1, "fixed")
    txns += monthly("BROADBAND CO", -3200, 3, "fixed")
    txns += monthly("MOBILE NETWORK", -1500, 7, "fixed")
    txns += monthly("STREAM ONE", -999, 12, "subscriptions")
    txns += monthly("STREAM TWO", -1099, 18, "subscriptions")
    txns += monthly("GYM MONTHLY", -2499, 25, "fun")
    # A weekly committed cost.
    txns += [_tx(d, -650, "LOCAL CLASS", "fun") for d in ("2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29")]
    # An annual insurance (three years, synthetic).
    txns += [_tx(d, -18000, "HOME INSURER") for d in ("2024-06-03", "2025-06-04", "2026-06-02")]

    detected = detect_recurring(txns, as_of=AS_OF, direction="out")
    by_key = {d.merchant_key: d.cadence for d in detected}
    assert len(detected) == 8
    assert by_key["flat share transfer"] == "monthly"
    assert by_key["broadband co"] == "monthly"
    assert by_key["mobile network"] == "monthly"
    assert by_key["stream one"] == "monthly"
    assert by_key["stream two"] == "monthly"
    assert by_key["gym monthly"] == "monthly"
    assert by_key["local class"] == "weekly"
    assert by_key["home insurer"] == "annual"
