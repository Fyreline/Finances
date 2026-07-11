"""Recurring-payment detection — docs/DATA_MODEL.md §3a, pure functions only
(no I/O; `insights_service.py` loads the trailing-13-month transaction rows
and calls these, then upserts `recurring_payments` preserving the user's
verdict — docs/ARCHITECTURE.md §3 "engines are pure functions over rows").

The algorithm, verbatim from docs/DATA_MODEL.md §3a:

1. **Group** by `merchant_key` (counterparty lowercased, digits/branch
   suffixes stripped), then within a group by amount cluster — amounts within
   ±12% or ±£1.50 (whichever is larger) of the running median join the
   cluster (so Tesco's variable grocery spend never clusters, a fixed £9.99
   sub does).
2. **Cadence test** per cluster with ≥3 occurrences: median gap → monthly
   27–36d / weekly 6–8 / quarterly 85–97 / annual 350–380; and a *bounded*
   number of outlier gaps (any single gap > 1.6× the median) may be set aside
   before classifying — a holiday-shifted payday or one delayed payment no
   longer vetoes an otherwise-overwhelmingly-consistent cluster (docs/phases/
   PHASE-13-rental-history-and-safe-to-spend-fix.md item D; the original rule
   discarded a real 25-occurrence monthly salary because one Christmas gap
   tripped it).
3. **Confidence** = 0.4·min(occ,6)/6 + 0.3·(1 − gap_variance_norm) +
   0.3·(1 − amount_spread_norm), floored at 0.35.
4. **Cancel-candidate flag** (advisory only): category ∈ {subscriptions, fun,
   other} AND tenure ≥ 4 months AND typical ≤ £25 AND no non-recurring
   transactions from the same merchant in 90 days.

Salary/rent arriving are detected the same way on **incoming** transactions
(`direction="in"`) — offered as income anchors, never auto-assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median, pstdev

_DATE_FMT = "%Y-%m-%d"

# median-gap windows per cadence (docs/DATA_MODEL.md §3a.2)
CADENCE_WINDOWS: dict[str, tuple[int, int]] = {
    "weekly": (6, 8),
    # Widened from (28, 33) → (27, 36) for a weekday-anchored payday (docs/phases/
    # PHASE-13 item D.1): "last Friday of the month" alternates naturally between
    # 28-day (4-week) and 35-day (5-week) calendar gaps — both are the same
    # monthly cadence, not anomalies. Still disjoint from weekly (≤8) and
    # quarterly (≥85), so nothing else can be mislabelled monthly.
    "monthly": (27, 36),
    "quarterly": (85, 97),
    "annual": (350, 380),
}
# nominal period length in days, for next_expected + lapsed detection
_CADENCE_DAYS: dict[str, int] = {"weekly": 7, "monthly": 30, "quarterly": 91, "annual": 365}
_CADENCE_MONTHS: dict[str, int] = {"monthly": 1, "quarterly": 3, "annual": 12}

_MAX_GAP_TOLERANCE = 1.6  # a single gap > 1.6× the median is an "outlier" beat
# How many outlier gaps a cluster may tolerate before it's judged genuinely
# irregular: `len(gaps) // _OUTLIER_GAP_DIVISOR` (integer floor). A short cluster
# (≤7 gaps) tolerates NONE — a single missed month in a 3-gap cluster is still
# rejected, preserving the original safety against false positives — while a
# long, dense cluster (a real salary's ~25 monthly gaps) survives one or two
# holiday-shifted beats (docs/phases/PHASE-13 item D.2).
_OUTLIER_GAP_DIVISOR = 8
_MIN_OCCURRENCES = 3
_CONFIDENCE_FLOOR = 0.35  # "floor at 0.35 to surface at all"
_AMOUNT_TOLERANCE_PCT = 0.12
_AMOUNT_TOLERANCE_MINOR = 150  # ±£1.50
# docs/DATA_MODEL.md §3a says "trailing 13 months", but 13 months cannot hold
# the 3 occurrences the same section's ≥3-occurrence + annual-cadence
# (350–380 day) rules require — a genuine internal contradiction (resolved
# here, doc corrected). Resolution: gather occurrences over a window wide
# enough for every cadence's ≥3 rule (≈3 years), then keep 13 months as a
# *recency* filter on `last_seen` — so a still-live annual insurance (last
# paid this month, first paid two years ago) surfaces, while a monthly sub
# cancelled 18 months ago does not.
_GATHER_MONTHS = 38
_RECENCY_MONTHS = 13

# cancel-candidate thresholds (docs/DATA_MODEL.md §3a.4)
CANCEL_CANDIDATE_CATEGORIES = {"subscriptions", "fun", "other"}
_CANCEL_MAX_AMOUNT_MINOR = 2500  # £25
_CANCEL_MIN_TENURE_DAYS = 120  # ~4 months
_CANCEL_NO_ACTIVITY_WINDOW_DAYS = 90


def _parse(value: str | date) -> date:
    return value if isinstance(value, date) else datetime.strptime(value, _DATE_FMT).date()


def _fmt(d: date) -> str:
    return d.strftime(_DATE_FMT)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, _days_in_month(year, month)))


@dataclass(frozen=True)
class TxnLike:
    """The structural shape the detector needs from a `transactions` row —
    kept DB-free so this engine stays import-light (mirrors
    `categorise.RuleLike`)."""

    local_date: str
    amount_minor: int  # signed (negative = out)
    counterparty: str | None
    category_key: str | None = None
    exclude_from_spending: bool = False


@dataclass
class DetectedRecurring:
    merchant_key: str
    label: str
    cadence: str
    typical_amount_minor: int  # signed median (negative = out), matches source direction
    amount_drift_pct: float
    first_seen: str
    last_seen: str
    next_expected: str | None
    occurrences: int
    confidence: float
    cancel_candidate: bool
    status_hint: str  # 'active' | 'lapsed' — service reconciles against user_verdict
    category_key: str | None
    earliest_amount_minor: int  # for the price-rise "old → new" tip
    latest_amount_minor: int
    gaps_days: list[int]  # observed calendar-day gaps between consecutive occurrences
    #                       (for payday_period_from_detected — an income anchor's
    #                       real period comes from its own history, not a rule)


def merchant_key(counterparty: str | None) -> str:
    """`"TESCO STORES 3412"` → `"tesco stores"` (docs/DATA_MODEL.md §3a.1):
    lowercase, strip digit runs (store/branch numbers) and any non-letter
    punctuation, collapse whitespace. Empty string for a null/blank
    counterparty (those never group)."""
    if not counterparty:
        return ""
    s = counterparty.lower()
    s = re.sub(r"[0-9]+", " ", s)  # store / branch numbers
    s = re.sub(r"[^a-z ]+", " ", s)  # punctuation, *, /, .com etc.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _within_amount_tolerance(amount_abs: int, running_median_abs: float) -> bool:
    tolerance = max(_AMOUNT_TOLERANCE_PCT * running_median_abs, _AMOUNT_TOLERANCE_MINOR)
    return abs(amount_abs - running_median_abs) <= tolerance


def cluster_by_amount(txns: list[TxnLike]) -> list[list[TxnLike]]:
    """Greedy amount clustering (docs/DATA_MODEL.md §3a.1). `txns` come in
    date order; each joins the first existing cluster whose running median it
    is within tolerance of, else opens a new cluster. Tesco's variable
    grocery amounts scatter into singletons (dropped later by the ≥3 rule);
    a fixed sub coalesces into one cluster."""
    clusters: list[list[TxnLike]] = []
    medians: list[float] = []
    for t in txns:
        amt = abs(t.amount_minor)
        placed = False
        for i, cluster in enumerate(clusters):
            if _within_amount_tolerance(amt, medians[i]):
                cluster.append(t)
                medians[i] = median([abs(x.amount_minor) for x in cluster])
                placed = True
                break
        if not placed:
            clusters.append([t])
            medians.append(float(amt))
    return clusters


def cadence_for_gaps(gaps: list[int]) -> str | None:
    """Median gap → cadence name, or None if no window fits or the cluster is
    genuinely irregular (docs/DATA_MODEL.md §3a.2, revised docs/phases/PHASE-13
    item D).

    Outlier handling: a gap greater than 1.6× the median is a missed/holiday-
    shifted beat. A *bounded* number of these (``len(gaps) // 8``, floor) is set
    aside and the cadence classified on the median of what remains — so a couple
    of real irregular gaps can't veto an otherwise-consistent pattern. If the
    outliers exceed that allowance, or too few regular gaps survive to trust a
    cadence, the cluster is rejected (unchanged behaviour for short/irregular
    clusters — the safety against false-positive "recurring" transfers is kept,
    just narrowed)."""
    if not gaps:
        return None
    med = median(gaps)
    if med <= 0:
        return None
    outliers = [g for g in gaps if g > _MAX_GAP_TOLERANCE * med]
    if len(outliers) > len(gaps) // _OUTLIER_GAP_DIVISOR:
        return None
    if outliers:
        kept = [g for g in gaps if g <= _MAX_GAP_TOLERANCE * med]
        if len(kept) < 2:  # too little regular evidence left to trust a cadence
            return None
        med = median(kept)
        if med <= 0:
            return None
    for name, (lo, hi) in CADENCE_WINDOWS.items():
        if lo <= med <= hi:
            return name
    return None


def confidence(occurrences: int, gaps: list[int], amounts_abs: list[int]) -> float:
    """docs/DATA_MODEL.md §3a.3, floored at 0.35. `gap_variance_norm` is the
    gaps' coefficient of variation (population stdev ÷ median), clamped to
    [0,1]; `amount_spread_norm` is the amounts' relative range
    ((max−min)÷median), clamped to [0,1] — both 0 for a perfectly regular,
    fixed-amount subscription (→ confidence 1.0 at ≥6 occurrences)."""
    occ_term = 0.4 * min(occurrences, 6) / 6

    med_gap = median(gaps) if gaps else 0
    gap_cv = (pstdev(gaps) / med_gap) if med_gap else 1.0
    gap_variance_norm = min(1.0, gap_cv)

    med_amt = median(amounts_abs) if amounts_abs else 0
    spread = ((max(amounts_abs) - min(amounts_abs)) / med_amt) if med_amt else 1.0
    amount_spread_norm = min(1.0, spread)

    raw = occ_term + 0.3 * (1 - gap_variance_norm) + 0.3 * (1 - amount_spread_norm)
    return max(_CONFIDENCE_FLOOR, round(raw, 3))


def next_expected(last_seen: date, cadence: str) -> str:
    if cadence == "weekly":
        return _fmt(last_seen + timedelta(days=7))
    return _fmt(_add_months(last_seen, _CADENCE_MONTHS[cadence]))


def _is_cancel_candidate(
    cluster: list[TxnLike],
    merchant_group: list[TxnLike],
    category_key: str | None,
    first_seen: date,
    last_seen: date,
    typical_abs: int,
    as_of: date,
) -> bool:
    """docs/DATA_MODEL.md §3a.4 — advisory only. "no non-recurring
    transactions in 90 days" = the merchant has no transaction *outside this
    cluster* dated within the last 90 days (top-ups/extras would signal
    active engagement). Kakeibo can't know real usage — the copy says "worth
    checking you still use this", never "unused"."""
    if category_key not in CANCEL_CANDIDATE_CATEGORIES:
        return False
    if (last_seen - first_seen).days < _CANCEL_MIN_TENURE_DAYS:
        return False
    if typical_abs > _CANCEL_MAX_AMOUNT_MINOR:
        return False
    cluster_ids = {id(t) for t in cluster}
    cutoff = as_of - timedelta(days=_CANCEL_NO_ACTIVITY_WINDOW_DAYS)
    for t in merchant_group:
        if id(t) in cluster_ids:
            continue
        if _parse(t.local_date) >= cutoff:
            return False  # a non-recurring purchase suggests active use
    return True


def detect_recurring(
    transactions: list[TxnLike], *, as_of: str | date, direction: str = "out"
) -> list[DetectedRecurring]:
    """The whole of docs/DATA_MODEL.md §3a. `direction="out"` over outgoing
    transactions builds the `recurring_payments` committed roster;
    `direction="in"` detects salary/rent income anchors the same way
    (offered, not auto-assumed). Trailing 13 months only. Deterministic
    order: highest confidence first (the UI orders by it — §3a.3)."""
    as_of_date = _parse(as_of)
    cutoff = _add_months(as_of_date, -_GATHER_MONTHS)
    recency_cutoff = _add_months(as_of_date, -_RECENCY_MONTHS)

    def keep(t: TxnLike) -> bool:
        if t.exclude_from_spending or not t.counterparty:
            return False
        if _parse(t.local_date) < cutoff:
            return False
        return t.amount_minor < 0 if direction == "out" else t.amount_minor > 0

    txns = [t for t in transactions if keep(t)]

    groups: dict[str, list[TxnLike]] = {}
    for t in txns:
        groups.setdefault(merchant_key(t.counterparty), []).append(t)

    results: list[DetectedRecurring] = []
    for mkey, group in groups.items():
        if not mkey:
            continue
        group_sorted = sorted(group, key=lambda t: t.local_date)
        for cluster in cluster_by_amount(group_sorted):
            if len(cluster) < _MIN_OCCURRENCES:
                continue
            cluster = sorted(cluster, key=lambda t: t.local_date)
            dates = [_parse(t.local_date) for t in cluster]
            gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
            cadence = cadence_for_gaps(gaps)
            if cadence is None:
                continue

            amounts_abs = [abs(t.amount_minor) for t in cluster]
            signed_median = round(median([t.amount_minor for t in cluster]))
            typical_abs = abs(signed_median)
            min_abs, max_abs = min(amounts_abs), max(amounts_abs)
            drift_pct = round((max_abs - min_abs) / min_abs * 100, 1) if min_abs else 0.0

            first_seen, last_seen = dates[0], dates[-1]
            conf = confidence(len(cluster), gaps, amounts_abs)
            category_key = next((t.category_key for t in reversed(cluster) if t.category_key), None)
            cancel = _is_cancel_candidate(
                cluster, group_sorted, category_key, first_seen, last_seen, typical_abs, as_of_date
            )
            lapsed = (as_of_date - last_seen).days > 2 * _CADENCE_DAYS[cadence]

            results.append(
                DetectedRecurring(
                    merchant_key=mkey,
                    label=cluster[-1].counterparty or mkey,  # freshest display name
                    cadence=cadence,
                    typical_amount_minor=signed_median,
                    amount_drift_pct=drift_pct,
                    first_seen=_fmt(first_seen),
                    last_seen=_fmt(last_seen),
                    next_expected=next_expected(last_seen, cadence),
                    occurrences=len(cluster),
                    confidence=conf,
                    cancel_candidate=cancel,
                    status_hint="lapsed" if lapsed else "active",
                    category_key=category_key,
                    earliest_amount_minor=cluster[0].amount_minor,
                    latest_amount_minor=cluster[-1].amount_minor,
                    gaps_days=gaps,
                )
            )

    # Recency filter: only surface a pattern whose most recent occurrence is
    # within the trailing 13 months (see _RECENCY_MONTHS note) — drops
    # long-dead subscriptions gathered from the wider occurrence window.
    results = [r for r in results if _parse(r.last_seen) >= recency_cutoff]

    # A merchant could yield two clusters at the same cadence (two distinct
    # subs) — the DB keys on (user, merchant_key, cadence), so collapse to the
    # highest-confidence one to keep the upsert deterministic.
    best: dict[tuple[str, str], DetectedRecurring] = {}
    for r in results:
        key = (r.merchant_key, r.cadence)
        if key not in best or r.confidence > best[key].confidence:
            best[key] = r
    return sorted(best.values(), key=lambda r: r.confidence, reverse=True)


def monthly_equivalent_minor(typical_amount_minor: int, cadence: str) -> int:
    """A cadence's normalised monthly cost, integer pence (docs/API.md §6 —
    `monthly_equivalent_minor`). Weekly ×52÷12, quarterly ÷3, annual ÷12.
    Sign is preserved from `typical_amount_minor`."""
    if cadence == "monthly":
        return typical_amount_minor
    if cadence == "weekly":
        return round(typical_amount_minor * 52 / 12)
    if cadence == "quarterly":
        return round(typical_amount_minor / 3)
    if cadence == "annual":
        return round(typical_amount_minor / 12)
    return typical_amount_minor
