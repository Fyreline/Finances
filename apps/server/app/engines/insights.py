"""Insight engines — docs/API.md §6a (safe-to-spend), §6b (monthly breakdown
+ verdicts), §6c (tips). Pure functions only; `routers/summary.py` +
`insights_service.py` assemble the DB rows and call these
(docs/ARCHITECTURE.md §3, which places safe-to-spend / verdicts / tips here).

Everything is integer pence, no floats in any money path. Every tip sentence
is an f-string template with numbers injected — there is no LLM call anywhere
in this module, so nothing can hallucinate financial advice (docs/API.md §6c).
Tone is advisory and calm: no "overspending", no "warning", no exclamation
marks (docs/DESIGN.md §6, PLAN §6 rule 8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean, median, pstdev

from .benchmarks import METHODOLOGY_NOTE, benchmark_for

_DATE_FMT = "%Y-%m-%d"


def _parse(value: str | date) -> date:
    return value if isinstance(value, date) else datetime.strptime(value, _DATE_FMT).date()


def _money(amount_minor: int) -> str:
    """`-1299 → "-£12.99"` — the engine's own formatter for tip/label text
    (the web has its own `money.ts`; this one exists so tip bodies read
    naturally in tests and API payloads). Minus sign, never parentheses
    (docs/ARCHITECTURE.md §6)."""
    sign = "-" if amount_minor < 0 else ""
    abs_minor = abs(amount_minor)
    return f"{sign}£{abs_minor // 100:,}.{abs_minor % 100:02d}"


def _money_whole(amount_minor: int) -> str:
    sign = "-" if amount_minor < 0 else ""
    return f"{sign}£{round(abs(amount_minor) / 100):,}"


# ===================================================================== §6a
def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _payday_date(year: int, month: int, payday_day: int) -> date:
    """Payday for a given month, clamped to the last day for a 29/30/31
    payday in a short month (docs/phases/PHASE-4-insights.md item 2 edge
    case)."""
    return date(year, month, min(payday_day, _days_in_month(year, month)))


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def payday_period(today: str | date, payday_day: int) -> tuple[date, date]:
    """The payday-anchored period containing `today`: from the most recent
    payday (inclusive) to the day before the next payday (docs/API.md §6a).
    Handles mid-period evaluation and short-month clamping."""
    t = _parse(today)
    this_payday = _payday_date(t.year, t.month, payday_day)
    if t >= this_payday:
        start = this_payday
        ny, nm = _next_month(t.year, t.month)
        nxt = _payday_date(ny, nm, payday_day)
    else:
        py, pm = _prev_month(t.year, t.month)
        start = _payday_date(py, pm, payday_day)
        nxt = this_payday
    return start, nxt - timedelta(days=1)


def payday_period_from_detected(
    last_seen: str | date,
    occurrences_gaps_days: list[int],
    today: str | date,
) -> tuple[date, date]:
    """The current payday period derived from a detected salary anchor's own
    observed history, rather than a modelled day-of-month rule (docs/phases/
    PHASE-11-payday-autodetect.md §1).

    `period_start` = the most recent detected salary transaction's date
    (`last_seen`); `period_end` = `period_start + median(gaps) - 1`, rolled
    forward by the same median gap repeatedly while `today` has already passed
    that estimated end (covers "opened the app a little into the next period
    before the next real salary transaction has synced" — a real, expected
    case, not an edge case).

    This deliberately does NOT model "last Friday of the month" as a weekday
    rule: the actual calendar-day gaps between consecutive real last-Friday
    salary dates already cluster in the same 28–33 day window as any monthly
    cadence, so median-gap-of-real-observations handles last-Friday, weekly,
    and roughly-monthly patterns uniformly, with no special case."""
    start = _parse(last_seen)
    t = _parse(today)
    med = round(median(occurrences_gaps_days)) if occurrences_gaps_days else 30
    if med < 1:  # degenerate (all occurrences on one day) — never zero-length
        med = 1
    end = start + timedelta(days=med - 1)
    while t > end:
        start = start + timedelta(days=med)
        end = start + timedelta(days=med - 1)
    return start, end


def months_to_next_31_jan(today: str | date) -> int:
    """Whole months from `today` to the next 31 January (the SA payment
    deadline) — the divisor for the 'auto' tax set-aside (docs/API.md §6a).
    At least 1 (never divide by zero, never front-load the whole bill onto a
    single day)."""
    t = _parse(today)
    year = t.year if (t.month, t.day) <= (1, 31) else t.year + 1
    target = date(year, 1, 31)
    months = (target.year - t.year) * 12 + (target.month - t.month)
    if t.day > target.day:
        months -= 1
    return max(1, months)


@dataclass(frozen=True)
class FinancialConfigLike:
    payday_day: int | None
    net_monthly_income_minor: int | None
    flat_share_minor: int | None
    buffer_minor: int
    tax_setaside_mode: str  # 'auto' | 'fixed' | 'off'
    tax_setaside_fixed_minor: int | None


@dataclass(frozen=True)
class DetectedIncome:
    """A salary anchor detected from real incoming transaction history
    (docs/phases/PHASE-11-payday-autodetect.md). Offered as the payday-period
    and net-income source when the user has NOT set those manually — always
    surfaced as `detected`, never silently presented as a typed-in figure."""

    net_income_minor: int  # the anchor's typical amount (positive magnitude)
    last_seen: date  # most recent detected salary transaction date
    gaps_days: list[int]  # observed calendar-day gaps between occurrences
    cadence: str
    occurrences: int
    confidence: float
    label: str  # freshest counterparty display name (e.g. the payroll name)


@dataclass(frozen=True)
class CommittedInput:
    label: str
    monthly_equivalent_minor: int  # positive magnitude


@dataclass(frozen=True)
class GoalSetAsideInput:
    key: str
    monthly_pledge_minor: int | None
    required_per_month_minor: int | None
    status: str  # 'on_track' | 'behind' | 'no_trend'


@dataclass
class SafeToSpendResult:
    setup_missing: list[str]
    safe_to_spend_minor: int | None
    income_minor: int
    net_income_minor: int
    rental_income_minor: int
    committed_minor: int
    goal_set_aside_minor: int
    tax_set_aside_minor: int
    buffer_minor: int
    spent_so_far_minor: int
    remaining_minor: int | None
    per_day_remaining_minor: int | None
    period_start: str | None
    period_end: str | None
    days_left: int | None
    # Provenance — the entire point of Phase 11: a figure the UI can trust to
    # label "you told us this" (manual) vs "we inferred this from your history"
    # (detected), or null while neither applies yet (setup_missing).
    payday_source: str | None = None  # 'manual' | 'detected' | None
    net_income_source: str | None = None  # 'manual' | 'detected' | None
    detected_income: dict | None = None  # human-readable detail when detected
    committed_items: list[dict] = field(default_factory=list)
    goal_items: list[dict] = field(default_factory=list)


_AMOUNT_TOLERANCE_PCT = 0.12
_AMOUNT_TOLERANCE_MINOR = 150


def _flat_share_already_committed(flat_share_minor: int, committed: list[CommittedInput]) -> bool:
    """docs/API.md §6a dedup: a recurring row that *is* the flat-share payment
    must not be counted twice. `financial_config` has no counterparty to match
    on (a documented gap — see API.md §6a), so we match on amount: an active
    recurring monthly-equivalent within ±12%/±£1.50 of the configured
    flat-share is treated as already representing it. Deliberately a *confident*
    match only — when unsure we do NOT suppress, because double-counting
    understates safe-to-spend (conservative) whereas wrongly suppressing would
    flatter the user (forbidden, docs/ARCHITECTURE.md §6)."""
    tolerance = max(_AMOUNT_TOLERANCE_PCT * flat_share_minor, _AMOUNT_TOLERANCE_MINOR)
    return any(abs(c.monthly_equivalent_minor - flat_share_minor) <= tolerance for c in committed)


def _goal_contribution(goal: GoalSetAsideInput) -> int:
    """docs/API.md §6a: a pledged goal uses its pledge; an unpledged
    house_deposit with a live trend uses its required-per-month; everything
    else (rebuild, or a no-trend deposit) rides on whatever is left."""
    if goal.monthly_pledge_minor is not None:
        return goal.monthly_pledge_minor
    if goal.key == "house_deposit" and goal.status != "no_trend" and goal.required_per_month_minor is not None:
        return goal.required_per_month_minor
    return 0


def resolve_period(
    config: FinancialConfigLike,
    today: str | date,
    detected_income: DetectedIncome | None,
) -> tuple[date, date] | None:
    """The current payday-anchored period, choosing the source the same way
    `safe_to_spend` does so period-scoped figures (rental income, discretionary
    spend) computed in the service layer can never disagree with the engine
    (docs/phases/PHASE-11-payday-autodetect.md §2). Manual `payday_day` wins;
    else a detected income anchor's own history; else `None` (period unknown —
    still in setup). Deterministic, so calling it twice gives the same window."""
    if config.payday_day is not None:
        return payday_period(today, config.payday_day)
    if detected_income is not None:
        return payday_period_from_detected(detected_income.last_seen, detected_income.gaps_days, today)
    return None


def safe_to_spend(
    *,
    config: FinancialConfigLike,
    today: str | date,
    committed: list[CommittedInput],
    rental_income_minor: int,
    goals: list[GoalSetAsideInput],
    discretionary_spent_minor: int,
    annual_tax_estimate_minor: int | None,
    detected_income: DetectedIncome | None = None,
) -> SafeToSpendResult:
    """docs/API.md §6a in one function. Returns `setup_missing` (and
    `safe_to_spend_minor=None`) when payday or take-home pay is neither set
    manually nor confidently detected, rather than pretending with defaults
    (docs/phases/PHASE-4-insights.md item 1). Otherwise every formula line is
    returned so the UI can draw the waterfall, and the segments (committed,
    goals, tax, buffer, spent, remaining) sum pence-exact to income by
    construction.

    Provenance (Phase 11): each of payday and net income resolves manual →
    detected → missing, per-field. **Manual always wins** — an explicitly set
    `payday_day`/`net_monthly_income_minor` is used exactly as before and its
    source is reported `'manual'`, never overridden by a detection. A detected
    salary anchor (`detected_income`) fills only the fields the user left
    unset, and is always surfaced as `'detected'` with an auditable detail
    block — never silently presented as a typed-in figure."""
    # Per-field provenance: manual beats detected beats absent.
    payday_source = (
        "manual" if config.payday_day is not None else ("detected" if detected_income is not None else None)
    )
    net_income_source = (
        "manual"
        if config.net_monthly_income_minor is not None
        else ("detected" if detected_income is not None else None)
    )

    detected_detail: dict | None = None
    if detected_income is not None and "detected" in (payday_source, net_income_source):
        med_gap = round(median(detected_income.gaps_days)) if detected_income.gaps_days else None
        detected_detail = {
            "label": detected_income.label,
            "typical_amount_minor": detected_income.net_income_minor,
            "cadence": detected_income.cadence,
            "median_gap_days": med_gap,
            "occurrences": detected_income.occurrences,
            "confidence": detected_income.confidence,
            "last_seen": _parse(detected_income.last_seen).strftime(_DATE_FMT),
        }

    setup_missing: list[str] = []
    if payday_source is None:
        setup_missing.append("payday_day")
    if net_income_source is None:
        setup_missing.append("net_monthly_income")
    if setup_missing:
        return SafeToSpendResult(
            setup_missing=setup_missing,
            safe_to_spend_minor=None,
            income_minor=0,
            net_income_minor=0,
            rental_income_minor=0,
            committed_minor=0,
            goal_set_aside_minor=0,
            tax_set_aside_minor=0,
            buffer_minor=config.buffer_minor,
            spent_so_far_minor=0,
            remaining_minor=None,
            per_day_remaining_minor=None,
            period_start=None,
            period_end=None,
            days_left=None,
            payday_source=payday_source,
            net_income_source=net_income_source,
            detected_income=detected_detail,
        )

    net_income = (
        config.net_monthly_income_minor
        if config.net_monthly_income_minor is not None
        else detected_income.net_income_minor  # type: ignore[union-attr]
    )
    income = net_income + rental_income_minor

    committed_total = sum(c.monthly_equivalent_minor for c in committed)
    flat_share = config.flat_share_minor or 0
    if flat_share > 0 and not _flat_share_already_committed(flat_share, committed):
        committed_total += flat_share
        committed_items = [*committed, CommittedInput(label="Flat share", monthly_equivalent_minor=flat_share)]
    else:
        committed_items = list(committed)

    goal_items = [{"key": g.key, "amount_minor": _goal_contribution(g)} for g in goals]
    goal_set_aside = sum(item["amount_minor"] for item in goal_items)

    if config.tax_setaside_mode == "fixed":
        tax_set_aside = config.tax_setaside_fixed_minor or 0
    elif config.tax_setaside_mode == "auto" and annual_tax_estimate_minor:
        # ceil(estimate ÷ months to next 31 Jan) — never flatters
        divisor = months_to_next_31_jan(today)
        tax_set_aside = -(-annual_tax_estimate_minor // divisor)
    else:  # 'off', or 'auto' while tax inputs are incomplete (estimate None/0)
        tax_set_aside = 0

    buffer = config.buffer_minor
    safe = income - committed_total - goal_set_aside - tax_set_aside - buffer
    remaining = safe - discretionary_spent_minor

    period = resolve_period(config, today, detected_income)
    assert period is not None  # guaranteed: payday_source is set past setup_missing
    start, end = period
    days_left = (end - _parse(today)).days + 1  # inclusive of today
    # Python's // floors toward −∞, which is exactly "floor" for a positive
    # remaining and stays honest (never flatters) for a negative one.
    per_day = remaining if days_left <= 0 else remaining // days_left

    return SafeToSpendResult(
        setup_missing=[],
        safe_to_spend_minor=safe,
        income_minor=income,
        net_income_minor=net_income,
        rental_income_minor=rental_income_minor,
        committed_minor=committed_total,
        goal_set_aside_minor=goal_set_aside,
        tax_set_aside_minor=tax_set_aside,
        buffer_minor=buffer,
        spent_so_far_minor=discretionary_spent_minor,
        remaining_minor=remaining,
        per_day_remaining_minor=per_day,
        period_start=start.strftime(_DATE_FMT),
        period_end=end.strftime(_DATE_FMT),
        days_left=max(0, days_left),
        payday_source=payday_source,
        net_income_source=net_income_source,
        detected_income=detected_detail,
        committed_items=[{"label": c.label, "monthly_equivalent_minor": c.monthly_equivalent_minor} for c in committed_items],
        goal_items=goal_items,
    )


# ===================================================================== §6b
@dataclass(frozen=True)
class CategoryMonthInput:
    key: str
    label: str
    viz_slot: int | None
    spend_minor: int  # this month, positive magnitude
    avg_3mo_minor: int  # trailing 3 months incl. this one, positive magnitude
    prev_avg_3mo_minor: int  # the 3 months before that (for trending, §6c)


def month_summary(
    *,
    month: str,
    income_minor: int,
    categories: list[CategoryMonthInput],
) -> dict:
    """docs/API.md §6b payload. `spend_minor` (the month total) is the sum of
    the categories' this-month spend. Each category carries its share, its
    delta vs its own trailing-3-month average, and a benchmark verdict (or
    null). `methodology_note` ships verbatim in every response — the bands are
    heuristic and must never read as precise (docs/API.md §6b)."""
    spend_total = sum(c.spend_minor for c in categories)

    cat_payloads: list[dict] = []
    for c in sorted(categories, key=lambda c: c.spend_minor, reverse=True):
        share_pct = round(c.spend_minor / spend_total * 100, 1) if spend_total else 0.0
        delta_vs_avg_pct = (
            round((c.spend_minor - c.avg_3mo_minor) / c.avg_3mo_minor * 100, 1) if c.avg_3mo_minor else 0.0
        )
        verdict = benchmark_for(c.key, c.avg_3mo_minor)
        cat_payloads.append(
            {
                "key": c.key,
                "label": c.label,
                "viz_slot": c.viz_slot,
                "spend_minor": c.spend_minor,
                "share_pct": share_pct,
                "avg_3mo_minor": c.avg_3mo_minor,
                "delta_vs_avg_pct": delta_vs_avg_pct,
                "benchmark": None
                if verdict is None
                else {
                    "band": verdict.band,
                    "band_bounds_minor": list(verdict.band_bounds_minor),
                    "source": verdict.source,
                    "as_of": verdict.as_of,
                    "severe": verdict.severe,
                },
            }
        )

    movers = sorted(
        ({"key": c.key, "delta_minor": c.spend_minor - c.avg_3mo_minor} for c in categories),
        key=lambda m: abs(m["delta_minor"]),
        reverse=True,
    )[:3]

    return {
        "month": month,
        "income_minor": income_minor,
        "spend_minor": spend_total,
        "net_minor": income_minor - spend_total,
        "categories": cat_payloads,
        "largest_movers": movers,
        "methodology_note": METHODOLOGY_NOTE,
    }


# ===================================================================== §6c
@dataclass
class TipResult:
    rule_key: str
    severity: str  # 'info' | 'worth_a_look'
    title: str
    body: str
    data: dict


# Each rule is its own pure function returning a TipResult or None (a
# fires/doesn't-fire pair per rule is a Phase-4 acceptance item). Multiples of
# the same rule are aggregated into one TipResult (the tips table keys on
# (user, rule_key, period), so at most one row per rule per period).

_TRENDING_MIN_RATIO = 1.20  # ≥20% over the previous 3-mo avg
_TRENDING_MIN_ABS_MINOR = 3000  # and ≥ £30/mo absolute
_PRICE_RISE_MIN_PCT = 10.0
_VARIANCE_THRESHOLD = 0.35  # stdev > 35% of mean
_EMERGENCY_MONTHS = 3


def tip_category_trending_up(movers: list[dict]) -> TipResult | None:
    """docs/API.md §6c `category_trending_up`. `movers` = categories whose
    3-mo avg is ≥20% over their previous 3-mo avg AND ≥£30/mo higher, each
    `{label, avg_3mo_minor, prev_avg_3mo_minor}`. States both numbers,
    suggests a look, not a cut."""
    qualifying = [
        m
        for m in movers
        if m["prev_avg_3mo_minor"] > 0
        and m["avg_3mo_minor"] >= m["prev_avg_3mo_minor"] * _TRENDING_MIN_RATIO
        and (m["avg_3mo_minor"] - m["prev_avg_3mo_minor"]) >= _TRENDING_MIN_ABS_MINOR
    ]
    if not qualifying:
        return None
    top = max(qualifying, key=lambda m: m["avg_3mo_minor"] - m["prev_avg_3mo_minor"])
    pct = round((top["avg_3mo_minor"] / top["prev_avg_3mo_minor"] - 1) * 100, 1)
    body = (
        f"{top['label']} averaged {_money(top['avg_3mo_minor'])} a month over the last three months, "
        f"up {pct}% from {_money(top['prev_avg_3mo_minor'])} the three months before. Might be worth a look."
    )
    return TipResult(
        "category_trending_up",
        "worth_a_look",
        f"{top['label']} is trending up",
        body,
        {"categories": qualifying},
    )


def tip_cancel_candidates(candidates: list[dict]) -> TipResult | None:
    """docs/API.md §6c `cancel_candidate`, from a recurring row flagged per
    DATA_MODEL §3a.4. `candidates` = `[{label, monthly_equivalent_minor}]`.
    Copy never asserts non-usage."""
    if not candidates:
        return None
    total = sum(c["monthly_equivalent_minor"] for c in candidates)
    if len(candidates) == 1:
        c = candidates[0]
        title = f"{c['label']} — worth a look"
        body = (
            f"{c['label']} is about {_money(c['monthly_equivalent_minor'])} a month and has been quietly "
            f"recurring for a while. Worth checking you still use this."
        )
    else:
        names = ", ".join(c["label"] for c in candidates)
        title = f"{len(candidates)} subscriptions worth a look"
        body = (
            f"{names} come to about {_money(total)} a month between them and have been quietly recurring. "
            f"Worth checking you still use these."
        )
    return TipResult("cancel_candidate", "worth_a_look", title, body, {"candidates": candidates})


def tip_price_rises(rises: list[dict]) -> TipResult | None:
    """docs/API.md §6c `price_rise`: recurring `amount_drift_pct` ≥ 10%.
    `rises` = `[{label, old_minor, new_minor, drift_pct}]`; names old vs new."""
    qualifying = [r for r in rises if r["drift_pct"] >= _PRICE_RISE_MIN_PCT]
    if not qualifying:
        return None
    top = max(qualifying, key=lambda r: r["drift_pct"])
    body = (
        f"{top['label']} has gone from {_money(top['old_minor'])} to {_money(top['new_minor'])} "
        f"(up {top['drift_pct']}%). Just so it is on your radar."
    )
    return TipResult("price_rise", "worth_a_look", f"{top['label']} costs more than it did", body, {"rises": qualifying})


def tip_discretionary_variance(monthly_discretionary_minor: list[int]) -> TipResult | None:
    """docs/API.md §6c `discretionary_variance`: stdev of the last 6 months'
    discretionary spend > 35% of its mean. Framed as predictability for
    safe-to-spend, not overspending."""
    values = [v for v in monthly_discretionary_minor if v is not None][-6:]
    if len(values) < 3:
        return None
    avg = mean(values)
    if avg <= 0:
        return None
    sd = pstdev(values)
    if sd <= _VARIANCE_THRESHOLD * avg:
        return None
    pct = round(sd / avg * 100, 1)
    body = (
        f"Your discretionary spend has swung by about {pct}% month to month lately "
        f"(around {_money(round(avg))} on average). Smoothing it out would make the safe-to-spend figure "
        f"steadier — nothing more than that."
    )
    return TipResult(
        "discretionary_variance",
        "info",
        "Discretionary spend varies a fair bit",
        body,
        {"mean_minor": round(avg), "stdev_minor": round(sd), "variance_pct": pct},
    )


def tip_emergency_fund_low(accessible_cash_minor: int, essential_monthly_minor: int) -> TipResult | None:
    """docs/API.md §6c `emergency_fund_low` (PLAN §4 S2): accessible cash
    < 3× essential monthly spend. Explicitly acknowledges the deposit-first
    trade-off — this is a deliberate choice, not a failing (PLAN §4 S2)."""
    if essential_monthly_minor <= 0:
        return None
    threshold = _EMERGENCY_MONTHS * essential_monthly_minor
    if accessible_cash_minor >= threshold:
        return None
    months_covered = round(accessible_cash_minor / essential_monthly_minor, 1)
    body = (
        f"Accessible cash covers about {months_covered} months of essential spending, under the usual "
        f"three-month mark. That is a fair trade-off while the deposit is the priority — worth keeping "
        f"in view rather than acting on today."
    )
    return TipResult(
        "emergency_fund_low",
        "info",
        "Emergency fund is on the lean side",
        body,
        {"accessible_cash_minor": accessible_cash_minor, "essential_monthly_minor": essential_monthly_minor,
         "months_covered": months_covered},
    )


def tip_tax_setaside_gap(has_tax_estimate: bool, setaside_mode: str) -> TipResult | None:
    """docs/API.md §6c `tax_setaside_gap` (PLAN §4 S5): a tax estimate exists
    but set-aside mode is 'off'. Informational."""
    if not has_tax_estimate or setaside_mode != "off":
        return None
    body = (
        "There is an estimated Self Assessment liability building up, but tax set-aside is switched off, "
        "so it is not reflected in safe-to-spend. Turning it on would keep January's bill from being a "
        "surprise."
    )
    return TipResult("tax_setaside_gap", "info", "Tax set-aside is switched off", body, {})


def tip_sa_registration_deadline(
    registered_for_sa: int | None, has_rental_activity: bool, today: str | date
) -> TipResult | None:
    """docs/API.md §6c `sa_registration_deadline` — the one tip allowed to be
    insistent, a real statutory deadline (TAX.md §6). Fires when SA
    registration is unconfirmed (NULL or 0), there is rental activity, and
    today is in [1 Jul, 5 Oct] of a year following a rental tax year. The 5
    October deadline is for the *previous* tax year's new rental income."""
    if registered_for_sa:  # 1 = registered → nothing to nudge
        return None
    if not has_rental_activity:
        return None
    t = _parse(today)
    if not (date(t.year, 7, 1) <= t <= date(t.year, 10, 5)):
        return None
    body = (
        f"Rental income means a Self Assessment registration may be due, and the deadline to register for "
        f"the previous tax year is 5 October {t.year}. It is worth confirming your registration status this "
        f"week, app or no app."
    )
    return TipResult(
        "sa_registration_deadline",
        "worth_a_look",  # the enum tops out here; the UI renders this one in the tax callout (DESIGN §4g)
        "Self Assessment registration deadline is close",
        body,
        {"deadline": f"{t.year}-10-05"},
    )
