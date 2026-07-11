"""Insight orchestration — the I/O layer between the pure `engines/insights`,
`engines/recurring`, `engines/benchmarks` and the DB (docs/ARCHITECTURE.md §3:
engines stay pure, this module loads rows + calls them + persists). Both
`routers/summary.py` / `routers/recurring.py` and the sync hook call in here;
neither re-implements the maths.

Recurring detection and tip generation are idempotent and safe to re-run —
they upsert on the same natural keys the schema already enforces and always
preserve the user's own decisions (`recurring_payments.user_verdict`, a
dismissed tip). So they run both after every sync (docs/phases/PHASE-4 item 3)
and are refreshed on read, so the endpoints work end-to-end even before a real
provider sync exists.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .balances import carry_forward_series, sum_series
from .dates import now_london
from .engines import insights, recurring
from .engines.goals import month_end_deltas, project_goal
from .models import (
    Account,
    BalanceSnapshot,
    Category,
    FinancialConfig,
    Goal,
    RecurringPayment,
    TaxConfig,
    Tip,
    Transaction,
)

logger = logging.getLogger(__name__)

_DB_TS_FMT = "%Y-%m-%d %H:%M:%S"


# --------------------------------------------------------------- shared loads
def _today_str() -> str:
    return now_london().strftime("%Y-%m-%d")


def _category_key_by_id(session: Session) -> dict[int, str]:
    return {c.id: c.key for c in session.scalars(select(Category)).all()}


def _category_kind_by_key(session: Session) -> dict[str, str]:
    return {c.key: c.kind for c in session.scalars(select(Category)).all()}


def _load_txns(session: Session, user_id: int) -> list[recurring.TxnLike]:
    key_by_id = _category_key_by_id(session)
    rows = session.scalars(
        select(Transaction).join(Account, Transaction.account_id == Account.id).where(Account.user_id == user_id)
    ).all()
    return [
        recurring.TxnLike(
            local_date=t.local_date,
            amount_minor=t.amount_minor,
            counterparty=t.counterparty,
            category_key=key_by_id.get(t.category_id) if t.category_id else None,
            exclude_from_spending=bool(t.exclude_from_spending),
        )
        for t in rows
    ]


# ===================================================================== recurring
def detect_for_user(session: Session, user_id: int, *, as_of: str | None = None) -> list[recurring.DetectedRecurring]:
    as_of = as_of or _today_str()
    return recurring.detect_recurring(_load_txns(session, user_id), as_of=as_of, direction="out")


def rebuild_recurring(session: Session, user_id: int, *, as_of: str | None = None) -> int:
    """Detect recurring outgoings and upsert `recurring_payments`, preserving
    each row's `user_verdict` and a `dismissed` status (docs/DATA_MODEL.md
    §3a.5). Returns the number of active detected patterns."""
    as_of = as_of or _today_str()
    detected = detect_for_user(session, user_id, as_of=as_of)
    key_id_by_key = {c.key: c.id for c in session.scalars(select(Category)).all()}

    existing = {
        (r.merchant_key, r.cadence): r
        for r in session.scalars(select(RecurringPayment).where(RecurringPayment.user_id == user_id)).all()
    }

    for d in detected:
        row = existing.get((d.merchant_key, d.cadence))
        category_id = key_id_by_key.get(d.category_key) if d.category_key else None
        if row is None:
            session.add(
                RecurringPayment(
                    user_id=user_id,
                    merchant_key=d.merchant_key,
                    label=d.label,
                    category_id=category_id,
                    cadence=d.cadence,
                    typical_amount_minor=d.typical_amount_minor,
                    amount_drift_pct=d.amount_drift_pct,
                    first_seen=d.first_seen,
                    last_seen=d.last_seen,
                    next_expected=d.next_expected,
                    occurrences=d.occurrences,
                    status=d.status_hint,
                    user_verdict=None,
                    confidence=d.confidence,
                )
            )
        else:
            row.label = d.label
            row.category_id = category_id
            row.typical_amount_minor = d.typical_amount_minor
            row.amount_drift_pct = d.amount_drift_pct
            row.first_seen = d.first_seen
            row.last_seen = d.last_seen
            row.next_expected = d.next_expected
            row.occurrences = d.occurrences
            row.confidence = d.confidence
            # Never resurrect a dismissed row, never overwrite a user verdict
            # (docs/DATA_MODEL.md §3a.5).
            if row.status != "dismissed":
                row.status = d.status_hint

    session.commit()
    return len(detected)


def list_recurring_payload(session: Session, user_id: int, *, as_of: str | None = None) -> dict:
    """docs/API.md §5 GET /api/recurring. Detection facts (amount, cadence,
    confidence, cancel-candidate) come fresh from the transactions; the user's
    verdict + dismissed status come from the persisted row. Only `active`
    (non-dismissed, non-cancelled) rows count toward `monthly_committed`."""
    as_of = as_of or _today_str()
    rebuild_recurring(session, user_id, as_of=as_of)
    detected = detect_for_user(session, user_id, as_of=as_of)
    stored = {
        (r.merchant_key, r.cadence): r
        for r in session.scalars(select(RecurringPayment).where(RecurringPayment.user_id == user_id)).all()
    }

    items: list[dict] = []
    monthly_committed = 0
    for d in detected:
        row = stored.get((d.merchant_key, d.cadence))
        verdict = row.user_verdict if row else None
        status = row.status if row else d.status_hint
        monthly_equiv = recurring.monthly_equivalent_minor(d.typical_amount_minor, d.cadence)
        if status == "active" and verdict != "cancelled":
            monthly_committed += abs(monthly_equiv)
        items.append(
            {
                "id": row.id if row else None,
                "label": d.label,
                "cadence": d.cadence,
                "typical_amount_minor": d.typical_amount_minor,
                "amount_drift_pct": d.amount_drift_pct,
                "first_seen": d.first_seen,
                "last_seen": d.last_seen,
                "next_expected": d.next_expected,
                "occurrences": d.occurrences,
                "status": status,
                "user_verdict": verdict,
                "confidence": d.confidence,
                "cancel_candidate": d.cancel_candidate,
                "monthly_equivalent_minor": monthly_equiv,
                "old_amount_minor": d.earliest_amount_minor,
                "new_amount_minor": d.latest_amount_minor,
            }
        )

    return {"recurring": items, "totals": {"monthly_committed_minor": monthly_committed}}


# ===================================================================== monthly spend
def _month_key(local_date: str) -> str:
    return local_date[:7]


def _shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    total = (y * 12 + (m - 1)) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


class _SpendMaps:
    """Per-month income, per-category spend, and discretionary spend, all
    positive-magnitude integer pence, computed once and reused across
    safe-to-spend / month summary / tips."""

    def __init__(self) -> None:
        self.income: dict[str, int] = {}
        self.by_category: dict[str, dict[str, int]] = {}
        self.discretionary: dict[str, int] = {}
        self.labels: dict[str, tuple[str, int | None]] = {}  # key -> (label, viz_slot)


def _spend_maps(session: Session, user_id: int) -> _SpendMaps:
    maps = _SpendMaps()
    cats = {c.id: c for c in session.scalars(select(Category)).all()}
    rows = session.scalars(
        select(Transaction).join(Account, Transaction.account_id == Account.id).where(Account.user_id == user_id)
    ).all()
    for t in rows:
        if t.exclude_from_spending:
            continue
        month = _month_key(t.local_date)
        cat = cats.get(t.category_id) if t.category_id else None
        kind = cat.kind if cat else None
        if t.amount_minor > 0 and kind != "transfer":
            maps.income[month] = maps.income.get(month, 0) + t.amount_minor
        elif t.amount_minor < 0 and kind in ("fixed", "discretionary"):
            spent = -t.amount_minor
            maps.by_category.setdefault(cat.key, {})
            maps.by_category[cat.key][month] = maps.by_category[cat.key].get(month, 0) + spent
            maps.labels[cat.key] = (cat.label, cat.viz_slot)
            if kind == "discretionary":
                maps.discretionary[month] = maps.discretionary.get(month, 0) + spent
    return maps


def _avg_over(month_map: dict[str, int], months: list[str]) -> int:
    return round(sum(month_map.get(m, 0) for m in months) / len(months)) if months else 0


def month_summary_payload(session: Session, user_id: int, month: str) -> dict:
    """docs/API.md §6b GET /api/summary/month/{yyyy-mm}."""
    maps = _spend_maps(session, user_id)
    this3 = [_shift_month(month, d) for d in (-2, -1, 0)]

    category_inputs: list[insights.CategoryMonthInput] = []
    for key, month_map in maps.by_category.items():
        this_month = month_map.get(month, 0)
        avg3 = _avg_over(month_map, this3)
        if this_month == 0 and avg3 == 0:
            continue  # a category with no spend this quarter isn't shown
        label, viz_slot = maps.labels.get(key, (key, None))
        category_inputs.append(
            insights.CategoryMonthInput(
                key=key,
                label=label,
                viz_slot=viz_slot,
                spend_minor=this_month,
                avg_3mo_minor=avg3,
                prev_avg_3mo_minor=_avg_over(month_map, [_shift_month(month, d) for d in (-5, -4, -3)]),
            )
        )

    return insights.month_summary(
        month=month, income_minor=maps.income.get(month, 0), categories=category_inputs
    )


# ===================================================================== safe-to-spend
def _financial_config_like(session: Session, user_id: int) -> insights.FinancialConfigLike:
    row = session.get(FinancialConfig, user_id)
    if row is None:
        return insights.FinancialConfigLike(
            payday_day=None,
            net_monthly_income_minor=None,
            flat_share_minor=None,
            buffer_minor=15000,
            tax_setaside_mode="auto",
            tax_setaside_fixed_minor=None,
        )
    return insights.FinancialConfigLike(
        payday_day=row.payday_day,
        net_monthly_income_minor=row.net_monthly_income_minor,
        flat_share_minor=row.flat_share_minor,
        buffer_minor=row.buffer_minor,
        tax_setaside_mode=row.tax_setaside_mode,
        tax_setaside_fixed_minor=row.tax_setaside_fixed_minor,
    )


def _goal_setaside_inputs(session: Session, user_id: int, today: str) -> list[insights.GoalSetAsideInput]:
    # Reuse the projection maths (routers/goals shares this shape) to get each
    # goal's status + required-per-month.
    goals = session.scalars(select(Goal).where(Goal.user_id == user_id)).all()
    owned = set(session.scalars(select(Account.id).where(Account.user_id == user_id)).all())
    out: list[insights.GoalSetAsideInput] = []
    for g in goals:
        try:
            ids = [int(i) for i in json.loads(g.source_account_ids or "[]") if int(i) in owned]
        except (TypeError, ValueError):
            ids = []
        series = sum_series(carry_forward_series(session, ids)) if ids else []
        current = series[-1][1] if series else g.baseline_minor
        deltas = month_end_deltas(series) if series else []
        proj = project_goal(
            target_minor=g.target_minor,
            target_date=g.target_date,
            current_minor=current,
            eval_date=today,
            deltas=deltas,
        )
        out.append(
            insights.GoalSetAsideInput(
                key=g.key,
                monthly_pledge_minor=g.monthly_pledge_minor,
                required_per_month_minor=proj.required_per_month_minor,
                status=proj.status,
            )
        )
    return out


def _period_rental_income(session: Session, user_id: int, start: date, end: date) -> int:
    rows = session.scalars(
        select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Account.user_id == user_id, Transaction.is_rental == 1, Transaction.amount_minor > 0)
    ).all()
    total = 0
    for t in rows:
        d = datetime.strptime(t.local_date, "%Y-%m-%d").date()
        if start <= d <= end:
            total += t.amount_minor
    return total


def _period_discretionary_spent(session: Session, user_id: int, start: date, end: date) -> int:
    cats = {c.id: c for c in session.scalars(select(Category)).all()}
    rows = session.scalars(
        select(Transaction).join(Account, Transaction.account_id == Account.id).where(Account.user_id == user_id)
    ).all()
    total = 0
    for t in rows:
        if t.exclude_from_spending or t.amount_minor >= 0 or t.category_id is None:
            continue
        cat = cats.get(t.category_id)
        if cat is None or cat.kind != "discretionary":
            continue
        d = datetime.strptime(t.local_date, "%Y-%m-%d").date()
        if start <= d <= end:
            total += -t.amount_minor
    return total


def _current_year_tax_estimate(session: Session, user_id: int, today: str) -> int | None:
    """The current tax year's estimated SA liability, for the 'auto' tax
    set-aside line (docs/API.md §6a; PLAN §4 S5). Reuses the tax router's own
    `year_summary_payload` — the same function behind the TaxPage and the tax
    bubble — so the set-aside figure can never drift from the estimate the
    user sees (the Phase-7 shared-payload precedent). Returns ``None`` while
    the estimator's inputs are incomplete (`estimate: null`), which the
    engine treats as a £0 set-aside — never a guessed number (TAX.md §0)."""
    from .routers.tax import year_summary_payload  # local import: routers import this module at startup

    from .dates import tax_year_of

    summary = year_summary_payload(session, user_id, tax_year_of(today))
    estimate = summary.get("estimate")
    return estimate["tax_due_minor"] if estimate else None


def _detect_income_anchor(session: Session, user_id: int, as_of: str) -> insights.DetectedIncome | None:
    """Pick the single best salary anchor from detected *incoming* recurring
    patterns (docs/phases/PHASE-11-payday-autodetect.md §2). This is the wiring
    that was always missing: `recurring.detect_recurring(..., direction="in")`
    has always supported income anchors, but nothing called it.

    Selection heuristic (documented so it is auditable, not a black box):

    - Detect incoming recurring patterns the same way outgoings are detected
      (same clustering/cadence/confidence thresholds — no new numbers invented).
    - Keep only **monthly** cadence at or above the existing confidence floor
      (`recurring._CONFIDENCE_FLOOR`). Monthly because `net_monthly_income`
      must mean a *monthly* figure — a weekly anchor's typical amount is a
      weekly sum and would misrepresent it. Monthly's 28–33 day window already
      absorbs "last Friday of the month" (its calendar-day gaps cluster there).
    - Among those, take the one with **by far the largest typical amount** —
      salary, distinct from the smaller recurring incoming amounts (refunds,
      interest, and — deliberately — rental income, which is smaller here and
      is summed separately by `_period_rental_income`, never folded into the
      salary figure).

    Returns `None` when there is no confident monthly income anchor yet (a new
    account, or too little/too irregular history) — the caller then falls back
    to `setup_missing`, never a guessed number."""
    detected = recurring.detect_recurring(_load_txns(session, user_id), as_of=as_of, direction="in")
    candidates = [
        d
        for d in detected
        if d.cadence == "monthly" and d.confidence >= recurring._CONFIDENCE_FLOOR
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda d: d.typical_amount_minor)
    return insights.DetectedIncome(
        net_income_minor=best.typical_amount_minor,  # positive (incoming)
        last_seen=datetime.strptime(best.last_seen, "%Y-%m-%d").date(),
        gaps_days=best.gaps_days,
        cadence=best.cadence,
        occurrences=best.occurrences,
        confidence=best.confidence,
        label=best.label,
    )


def safe_to_spend_payload(session: Session, user_id: int, *, today: str | None = None) -> dict:
    """docs/API.md §6a GET /api/summary/safe-to-spend."""
    today = today or _today_str()
    config = _financial_config_like(session, user_id)

    # Assemble committed obligations from the active recurring roster.
    committed: list[insights.CommittedInput] = []
    for d in detect_for_user(session, user_id, as_of=today):
        monthly = abs(recurring.monthly_equivalent_minor(d.typical_amount_minor, d.cadence))
        committed.append(insights.CommittedInput(label=d.label, monthly_equivalent_minor=monthly))

    # Detect a salary anchor to fill payday/income the user hasn't set manually
    # (manual always wins — the engine only uses this for unset fields).
    detected_income = _detect_income_anchor(session, user_id, today)

    # The period can now come from either a manual payday or the detected
    # anchor's own history — resolve it once, so the period-scoped figures and
    # the engine agree.
    period = insights.resolve_period(config, today, detected_income)
    goals = _goal_setaside_inputs(session, user_id, today) if period is not None else []

    rental_income = 0
    discretionary_spent = 0
    if period is not None:
        start, end = period
        rental_income = _period_rental_income(session, user_id, start, end)
        discretionary_spent = _period_discretionary_spent(session, user_id, start, end)

    result = insights.safe_to_spend(
        config=config,
        today=today,
        committed=committed,
        rental_income_minor=rental_income,
        goals=goals,
        discretionary_spent_minor=discretionary_spent,
        annual_tax_estimate_minor=_current_year_tax_estimate(session, user_id, today),
        detected_income=detected_income,
    )
    return {
        "safe_to_spend_minor": result.safe_to_spend_minor,
        "setup_missing": result.setup_missing,
        "income_minor": result.income_minor,
        "net_income_minor": result.net_income_minor,
        "rental_income_minor": result.rental_income_minor,
        "committed_minor": result.committed_minor,
        "goal_set_aside_minor": result.goal_set_aside_minor,
        "tax_set_aside_minor": result.tax_set_aside_minor,
        "buffer_minor": result.buffer_minor,
        "spent_so_far_minor": result.spent_so_far_minor,
        "remaining_minor": result.remaining_minor,
        "per_day_remaining_minor": result.per_day_remaining_minor,
        "period": {"start": result.period_start, "end": result.period_end},
        "days_left": result.days_left,
        "payday_source": result.payday_source,
        "net_income_source": result.net_income_source,
        "detected_income": result.detected_income,
        "committed_items": result.committed_items,
        "goal_items": result.goal_items,
    }


# ===================================================================== tips
def _essential_monthly(session: Session, user_id: int, today: str) -> int:
    """Trailing-3-month average of fixed commitments + groceries (the S2
    'essential' basket, PLAN §4 S2)."""
    maps = _spend_maps(session, user_id)
    kind_by_key = _category_kind_by_key(session)
    this3 = [_shift_month(today[:7], d) for d in (-2, -1, 0)]
    total = 0
    for key, month_map in maps.by_category.items():
        if kind_by_key.get(key) == "fixed" or key == "groceries":
            total += _avg_over(month_map, this3)
    return total


def _accessible_cash(session: Session, user_id: int) -> int:
    """Latest balance across current/savings/manual accounts (not investment)
    — the accessible-cash figure for the emergency-fund tip."""
    accounts = session.scalars(
        select(Account).where(Account.user_id == user_id, Account.kind.in_(("current", "savings")))
    ).all()
    total = 0
    for a in accounts:
        snap = session.scalar(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.account_id == a.id)
            .order_by(BalanceSnapshot.local_date.desc())
            .limit(1)
        )
        if snap:
            total += snap.balance_minor
    return total


def accessible_cash_minor(session: Session, user_id: int) -> int:
    """Public wrapper over `_accessible_cash` — reused by
    `engines/emergency_fund.py`'s caller in `routers/accounts.py`
    (docs/phases/PHASE-9-personal-goals.md §2) as well as the
    `emergency_fund_low` tip above, so the two surfaces can never disagree
    on what "accessible cash" means."""
    return _accessible_cash(session, user_id)


def essential_monthly_minor(session: Session, user_id: int, today: str) -> int:
    """Public wrapper over `_essential_monthly` — see `accessible_cash_minor`."""
    return _essential_monthly(session, user_id, today)


def _has_rental_activity(session: Session, user_id: int) -> bool:
    if session.scalar(
        select(Transaction.id)
        .join(Account, Transaction.account_id == Account.id)
        .where(Account.user_id == user_id, Transaction.is_rental == 1)
        .limit(1)
    ):
        return True
    tax = session.get(TaxConfig, user_id)
    return bool(tax and tax.monthly_rent_minor)


def generate_tips(session: Session, user_id: int, period: str, *, as_of: str | None = None) -> list[insights.TipResult]:
    """Assemble every §6c rule's inputs from the DB and collect the tips that
    fire. Pure rule functions live in `engines/insights`; this only gathers
    numbers and never writes copy of its own."""
    as_of = as_of or _today_str()
    maps = _spend_maps(session, user_id)

    # trending: each spending category's recent vs prior 3-month average
    this3 = [_shift_month(period, d) for d in (-2, -1, 0)]
    prev3 = [_shift_month(period, d) for d in (-5, -4, -3)]
    movers = [
        {
            "label": maps.labels.get(key, (key, None))[0],
            "avg_3mo_minor": _avg_over(month_map, this3),
            "prev_avg_3mo_minor": _avg_over(month_map, prev3),
        }
        for key, month_map in maps.by_category.items()
    ]

    detected = detect_for_user(session, user_id, as_of=as_of)
    stored = {
        (r.merchant_key, r.cadence): r
        for r in session.scalars(select(RecurringPayment).where(RecurringPayment.user_id == user_id)).all()
    }
    cancel_candidates = []
    price_rises = []
    for d in detected:
        row = stored.get((d.merchant_key, d.cadence))
        verdict = row.user_verdict if row else None
        if d.cancel_candidate and verdict not in ("keep", "cancelled"):
            cancel_candidates.append(
                {"label": d.label, "monthly_equivalent_minor": abs(recurring.monthly_equivalent_minor(d.typical_amount_minor, d.cadence))}
            )
        if d.amount_drift_pct >= 10.0:
            price_rises.append(
                {"label": d.label, "old_minor": abs(d.earliest_amount_minor), "new_minor": abs(d.latest_amount_minor), "drift_pct": d.amount_drift_pct}
            )

    discretionary_series = [maps.discretionary.get(_shift_month(period, d), 0) for d in range(-5, 1)]

    tax = session.get(TaxConfig, user_id)
    config = _financial_config_like(session, user_id)

    candidates = [
        insights.tip_category_trending_up(movers),
        insights.tip_cancel_candidates(cancel_candidates),
        insights.tip_price_rises(price_rises),
        insights.tip_discretionary_variance(discretionary_series),
        insights.tip_tax_setaside_gap(has_tax_estimate=False, setaside_mode=config.tax_setaside_mode),
        insights.tip_sa_registration_deadline(
            registered_for_sa=(tax.registered_for_sa if tax else None),
            has_rental_activity=_has_rental_activity(session, user_id),
            today=as_of,
        ),
    ]
    # Emergency-fund tip only when the S2 emergency_fund goal has been set up.
    if session.scalar(select(Goal).where(Goal.user_id == user_id, Goal.key == "emergency_fund")):
        candidates.append(
            insights.tip_emergency_fund_low(
                accessible_cash_minor=_accessible_cash(session, user_id),
                essential_monthly_minor=_essential_monthly(session, user_id, as_of),
            )
        )
    return [t for t in candidates if t is not None]


def rebuild_tips(session: Session, user_id: int, period: str, *, as_of: str | None = None) -> int:
    """Upsert the period's tips, preserving a dismissed tip so it never
    resurfaces the same period (docs/API.md §6c). Returns the count of live
    (non-dismissed) tips."""
    fresh = {t.rule_key: t for t in generate_tips(session, user_id, period, as_of=as_of)}
    existing = {
        t.rule_key: t
        for t in session.scalars(select(Tip).where(Tip.user_id == user_id, Tip.period == period)).all()
    }
    for rule_key, tip in fresh.items():
        row = existing.get(rule_key)
        data_json = json.dumps(tip.data)
        if row is None:
            session.add(
                Tip(
                    user_id=user_id,
                    rule_key=rule_key,
                    period=period,
                    severity=tip.severity,
                    title=tip.title,
                    body=tip.body,
                    data_json=data_json,
                    dismissed=0,
                )
            )
        else:
            row.severity, row.title, row.body, row.data_json = tip.severity, tip.title, tip.body, data_json
    # A rule that no longer fires: drop its non-dismissed row so stale tips
    # don't linger (a dismissed one stays, harmless, and keeps it dismissed).
    for rule_key, row in existing.items():
        if rule_key not in fresh and not row.dismissed:
            session.delete(row)
    session.commit()
    return sum(1 for rule_key in fresh if not (existing.get(rule_key) and existing[rule_key].dismissed))


def list_tips_payload(session: Session, user_id: int, period: str, *, as_of: str | None = None) -> dict:
    rebuild_tips(session, user_id, period, as_of=as_of)
    rows = session.scalars(
        select(Tip).where(Tip.user_id == user_id, Tip.period == period, Tip.dismissed == 0).order_by(Tip.id)
    ).all()
    return {
        "tips": [
            {
                "id": t.id,
                "rule_key": t.rule_key,
                "severity": t.severity,
                "title": t.title,
                "body": t.body,
                "data": json.loads(t.data_json) if t.data_json else {},
            }
            for t in rows
        ]
    }
