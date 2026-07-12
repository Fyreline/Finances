"""SQLAlchemy 2.x ORM models — mirrors docs/DATA_MODEL.md §1-7 exactly.

Timestamps are UTC ``"%Y-%m-%d %H:%M:%S"`` strings (household convention);
**all money columns are integer pence, signed from the user's perspective
(negative = out)**, names ending ``_minor`` (docs/ARCHITECTURE.md §6 — a
float in a money path is a review-blocker). Provider ids are stored verbatim
as TEXT and are the idempotency keys for sync — a re-run must never
duplicate a row.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# datetime('now') default, shared by every *_at/created_at column that uses it.
NOW = text("datetime('now')")


# ============ 1. Identity & infrastructure (ports from Michi) ============
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(nullable=False, unique=True)  # lower()
    display_name: Mapped[str] = mapped_column(nullable=False)  # refreshed at every login
    mishka_user_id: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)
    # {dashboard_tiles_order: [...], hidden_suggestions: ["S4", ...]}
    # (theme is handled client-side, not stored here — docs/DATA_MODEL.md §1)
    settings_json: Mapped[str] = mapped_column(nullable=False, server_default=text("'{}'"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(nullable=False, unique=True)
    expires_at: Mapped[str] = mapped_column(nullable=False)
    revoked: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (Index("idx_refresh_user", "user_id", "revoked"),)


# ============ 2. Accounts, balances, transactions ============
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(nullable=False)  # 'starling' | 'trading212' | 'manual'
    provider_account_uid: Mapped[str | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # 'current' | 'savings' | 'investment'
    currency: Mapped[str] = mapped_column(nullable=False, server_default=text("'GBP'"))
    default_category_uid: Mapped[str | None] = mapped_column(nullable=True)
    include_in_networth: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_uid", name="uq_accounts_provider_uid"),
    )


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    captured_at: Mapped[str] = mapped_column(nullable=False)
    local_date: Mapped[str] = mapped_column(nullable=False)  # Europe/London date — the trend axis
    balance_minor: Mapped[int] = mapped_column(nullable=False)
    available_minor: Mapped[int | None] = mapped_column(nullable=True)
    detail_json: Mapped[str | None] = mapped_column(nullable=True)  # server-side only

    __table_args__ = (
        UniqueConstraint("account_id", "local_date", name="uq_snapshot_account_date"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    provider_uid: Mapped[str] = mapped_column(nullable=False)
    amount_minor: Mapped[int] = mapped_column(nullable=False)  # signed (negative = out)
    transaction_time: Mapped[str] = mapped_column(nullable=False)  # provider timestamp, UTC
    local_date: Mapped[str] = mapped_column(nullable=False)  # Europe/London — ALL month grouping
    settled: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    counterparty: Mapped[str | None] = mapped_column(nullable=True)
    reference: Mapped[str | None] = mapped_column(nullable=True)
    provider_category: Mapped[str | None] = mapped_column(nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    category_source: Mapped[str] = mapped_column(nullable=False, server_default=text("'provider'"))
    is_rental: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    exclude_from_spending: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    raw_json: Mapped[str] = mapped_column(nullable=False)  # never sent to the SPA

    __table_args__ = (
        UniqueConstraint("account_id", "provider_uid", name="uq_txn_account_provider_uid"),
        Index("idx_txn_account_date", "account_id", "local_date"),
        Index("idx_txn_category_date", "category_id", "local_date"),
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(nullable=False)
    started_at: Mapped[str] = mapped_column(nullable=False)
    finished_at: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False)  # 'ok' | 'error' | 'not_configured'
    new_rows: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    detail: Mapped[str | None] = mapped_column(nullable=True)


# ============ 3. Categories, rules, recurring payments ============
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(nullable=False, unique=True)
    label: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # income|fixed|discretionary|rental|transfer
    viz_slot: Mapped[int | None] = mapped_column(nullable=True)  # stable 1..8, never reshuffled
    sort: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    priority: Mapped[int] = mapped_column(nullable=False)
    match_field: Mapped[str] = mapped_column(nullable=False)  # counterparty|reference|provider_category
    pattern: Mapped[str] = mapped_column(nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    set_is_rental: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    set_exclude: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


class RecurringPayment(Base):
    __tablename__ = "recurring_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    merchant_key: Mapped[str] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    cadence: Mapped[str] = mapped_column(nullable=False)  # monthly|weekly|quarterly|annual
    typical_amount_minor: Mapped[int] = mapped_column(nullable=False)
    amount_drift_pct: Mapped[float] = mapped_column(nullable=False, server_default=text("0"))
    first_seen: Mapped[str] = mapped_column(nullable=False)
    last_seen: Mapped[str] = mapped_column(nullable=False)
    next_expected: Mapped[str | None] = mapped_column(nullable=True)
    occurrences: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, server_default=text("'active'"))
    user_verdict: Mapped[str | None] = mapped_column(nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "merchant_key", "cadence", name="uq_recurring_user_merchant_cadence"),
    )


# ============ 4. Goals & projections ============
class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(nullable=False, unique=True)
    label: Mapped[str] = mapped_column(nullable=False)
    target_minor: Mapped[int | None] = mapped_column(nullable=True)  # NULL = open-ended
    target_date: Mapped[str | None] = mapped_column(nullable=True)
    baseline_minor: Mapped[int] = mapped_column(nullable=False)
    baseline_date: Mapped[str] = mapped_column(nullable=False)
    source_account_ids: Mapped[str] = mapped_column(nullable=False, server_default=text("'[]'"))  # JSON list
    monthly_pledge_minor: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ 5. User financial config (DB, not env) ============
class FinancialConfig(Base):
    __tablename__ = "financial_config"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    payday_day: Mapped[int | None] = mapped_column(nullable=True)
    # Weekday-based manual payday (docs/phases/PHASE-14 item 1c) — an alternative
    # to the numeric day-of-month `payday_day`, expressing "the Nth (or last)
    # weekday of the month" (e.g. last Friday), which a literal 1–31 can't. Both
    # nullable, self-heal via app/schema_sync.py. Mutually exclusive with
    # payday_day (the PUT clears the other pair); resolve_period() gives payday_day
    # precedence if somehow both are set. weekday is date.weekday(): 0=Mon..6=Sun.
    payday_weekday: Mapped[int | None] = mapped_column(nullable=True)
    payday_week_position: Mapped[str | None] = mapped_column(nullable=True)  # first|second|third|fourth|last
    net_monthly_income_minor: Mapped[int | None] = mapped_column(nullable=True)
    flat_share_minor: Mapped[int | None] = mapped_column(nullable=True)
    buffer_minor: Mapped[int] = mapped_column(nullable=False, server_default=text("15000"))
    tax_setaside_mode: Mapped[str] = mapped_column(nullable=False, server_default=text("'auto'"))
    tax_setaside_fixed_minor: Mapped[int | None] = mapped_column(nullable=True)
    # S4 contractor gap (docs/phases/PHASE-9-personal-goals.md §3). Both NULL
    # until the user answers — NEVER a false default (pension_contributing
    # defaulting to 0 would silently assert "not paying in", which nobody
    # has confirmed). fte_conversion_target_date, once set, seeds/updates the
    # 'fte_runway' goal row (docs/DATA_MODEL.md §4) via routers/summary.py.
    pension_contributing: Mapped[int | None] = mapped_column(nullable=True)  # NULL=unanswered, 0=no, 1=yes
    fte_conversion_target_date: Mapped[str | None] = mapped_column(nullable=True)
    updated_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


class TaxConfig(Base):
    __tablename__ = "tax_config"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    monthly_rent_minor: Mapped[int | None] = mapped_column(nullable=True)
    letting_agent: Mapped[str | None] = mapped_column(nullable=True)
    agent_fee_pct: Mapped[float | None] = mapped_column(nullable=True)
    has_mortgage: Mapped[int | None] = mapped_column(nullable=True)  # NULL = unknown
    annual_mortgage_interest_minor: Mapped[int | None] = mapped_column(nullable=True)
    # Rate + outstanding balance — an honest, visibly-flagged fallback when the
    # exact certificate figure above isn't known (docs/phases/
    # PHASE-10-post-launch-fixes.md item 6, docs/TAX.md §2). The certificate
    # figure always wins when both are set; the estimate it derives carries an
    # `assumptions` line, never presented as the exact number.
    mortgage_rate_pct: Mapped[float | None] = mapped_column(nullable=True)
    mortgage_balance_minor: Mapped[int | None] = mapped_column(nullable=True)  # OUTSTANDING, not original loan
    is_leasehold: Mapped[int | None] = mapped_column(nullable=True)
    registered_for_sa: Mapped[int | None] = mapped_column(nullable=True)  # NULL = unknown
    utr: Mapped[str | None] = mapped_column(nullable=True)
    employment_gross_annual_minor: Mapped[int | None] = mapped_column(nullable=True)
    updated_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


# ============ 6. Tax ledger & documents ============
class TaxYear(Base):
    __tablename__ = "tax_years"

    key: Mapped[str] = mapped_column(primary_key=True)  # '2026-27'
    start_date: Mapped[str] = mapped_column(nullable=False)
    end_date: Mapped[str] = mapped_column(nullable=False)


class TaxDocument(Base):
    __tablename__ = "tax_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tax_year: Mapped[str] = mapped_column(ForeignKey("tax_years.key"), nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)  # gmail|manual
    gmail_message_id: Mapped[str | None] = mapped_column(nullable=True, unique=True)
    doc_type: Mapped[str] = mapped_column(nullable=False)
    received_at: Mapped[str] = mapped_column(nullable=False)
    from_addr: Mapped[str | None] = mapped_column(nullable=True)
    subject: Mapped[str | None] = mapped_column(nullable=True)
    file_path: Mapped[str] = mapped_column(nullable=False)  # under tax-documents/<tax_year>/
    amount_minor: Mapped[int | None] = mapped_column(nullable=True)
    amount_confidence: Mapped[str] = mapped_column(nullable=False, server_default=text("'none'"))
    reviewed: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(nullable=True)


class RentalLedgerEntry(Base):
    __tablename__ = "rental_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tax_year: Mapped[str] = mapped_column(ForeignKey("tax_years.key"), nullable=False)
    local_date: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False)  # income|expense
    expense_type: Mapped[str | None] = mapped_column(nullable=True)
    amount_minor: Mapped[int] = mapped_column(nullable=False)  # positive; kind carries the sign
    source: Mapped[str] = mapped_column(nullable=False)  # transaction|document|manual
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    tax_document_id: Mapped[int | None] = mapped_column(ForeignKey("tax_documents.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)

    __table_args__ = (Index("idx_rental_ledger_year_kind", "tax_year", "kind"),)


# ============ 7. Savings deals, tips, splits ============
class DealRun(Base):
    __tablename__ = "deal_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_at: Mapped[str] = mapped_column(nullable=False)
    method: Mapped[str] = mapped_column(nullable=False)  # agent_research|manual
    sources_json: Mapped[str] = mapped_column(nullable=False)  # [{url, fetched_at}]
    file_path: Mapped[str] = mapped_column(nullable=False)


class SavingsDeal(Base):
    __tablename__ = "savings_deals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deal_run_id: Mapped[int] = mapped_column(ForeignKey("deal_runs.id"), nullable=False)
    provider: Mapped[str] = mapped_column(nullable=False)
    product: Mapped[str] = mapped_column(nullable=False)
    aer_pct: Mapped[float] = mapped_column(nullable=False)
    access: Mapped[str] = mapped_column(nullable=False)  # easy|notice|limited_withdrawals
    min_deposit_minor: Mapped[int | None] = mapped_column(nullable=True)
    fscs: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    is_isa: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    source_url: Mapped[str] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(nullable=True)


class Tip(Base):
    __tablename__ = "tips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    rule_key: Mapped[str] = mapped_column(nullable=False)
    period: Mapped[str] = mapped_column(nullable=False)  # '2026-07'
    severity: Mapped[str] = mapped_column(nullable=False)  # info|worth_a_look (no 'alarm')
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(nullable=False)
    data_json: Mapped[str | None] = mapped_column(nullable=True)
    dismissed: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))

    __table_args__ = (
        UniqueConstraint("user_id", "rule_key", "period", name="uq_tips_user_rule_period"),
    )


# ============ 8. Gift-occasion budgets & personal wants (docs/phases/PHASE-9-personal-goals.md §4-5) ============
class GiftOccasion(Base):
    """Goal 10 (docs/PLAN.md §3 row 10) — a sinking-fund-style budget for one
    gift-giving occasion. `label`/`limit_minor`/`target_date` are 100%
    user-entered at runtime; never seeded, never a real occasion name in a
    fixture (docs/PRIVATE.md redaction scheme)."""

    __tablename__ = "gift_occasions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(nullable=False)
    limit_minor: Mapped[int | None] = mapped_column(nullable=True)  # NULL = no limit set yet, never invented
    target_date: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)


class GiftItem(Base):
    __tablename__ = "gift_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occasion_id: Mapped[int] = mapped_column(ForeignKey("gift_occasions.id"), nullable=False)
    label: Mapped[str] = mapped_column(nullable=False)
    price_minor: Mapped[int] = mapped_column(nullable=False)
    bought: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    bought_date: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (Index("idx_gift_items_occasion", "occasion_id"),)


class WantItem(Base):
    """Goal 11 (docs/PLAN.md §3 row 11) — a personal-wants wishlist item; the
    affordability verdict (`engines/affordability.py`) is always computed
    live, never stored, so it can never go stale against the goals/
    safe-to-spend it reads."""

    __tablename__ = "want_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(nullable=False)
    price_minor: Mapped[int] = mapped_column(nullable=False)
    bought: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(nullable=False, server_default=NOW)

    __table_args__ = (Index("idx_want_items_user", "user_id"),)


class SplitEntry(Base):
    """Warikan (only used if PLAN.md §4 S3 is accepted)."""

    __tablename__ = "split_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    local_date: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    total_minor: Mapped[int] = mapped_column(nullable=False)
    my_share_minor: Mapped[int] = mapped_column(nullable=False)
    paid_by: Mapped[str] = mapped_column(nullable=False)  # me|partner
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    settled: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    settled_at: Mapped[str | None] = mapped_column(nullable=True)


# ============ Category seed (docs/DATA_MODEL.md §3 taxonomy + docs/DESIGN.md §2b slots) ============
# (key, label, kind, viz_slot, sort). viz_slot is None for categories that
# never appear in the spending-breakdown chart (income/rental/transfer kinds
# always render with the semantic gain/setaside token instead — docs/DESIGN.md
# §2b: "never reuse a category colour for a non-category series").
CATEGORY_SEED: list[tuple[str, str, str, int | None, int]] = [
    ("housing", "Housing", "fixed", 1, 10),
    ("bills", "Bills", "fixed", 1, 20),
    ("groceries", "Groceries", "discretionary", 2, 30),
    ("eating_out", "Eating out", "discretionary", 3, 40),
    ("fun", "Fun", "discretionary", 4, 50),
    ("subscriptions", "Subscriptions", "discretionary", 4, 60),
    ("transport", "Transport", "discretionary", 5, 70),
    ("shopping", "Shopping", "discretionary", 6, 80),
    ("gifts", "Gifts", "discretionary", 6, 90),
    ("holidays", "Holidays", "discretionary", 7, 100),
    ("health", "Health", "discretionary", 8, 110),
    ("other", "Everything else", "discretionary", 8, 120),
    ("salary", "Salary", "income", None, 200),
    ("rental_income", "Rental income", "rental", None, 210),
    ("rental_expense", "Rental expense", "rental", None, 220),
    ("savings_transfer", "Savings transfer", "transfer", None, 230),
    ("transfer_self", "Transfer to self", "transfer", None, 240),
]


def seed_categories(session) -> None:  # noqa: ANN001 — sqlalchemy Session, avoid import cycle
    """Idempotent upsert of the fixed category taxonomy — safe to call on
    every startup (docs/phases/PHASE-1-scaffold.md item 2)."""
    from sqlalchemy import select

    existing = {c.key: c for c in session.scalars(select(Category)).all()}
    for key, label, kind, viz_slot, sort in CATEGORY_SEED:
        if key in existing:
            row = existing[key]
            row.label, row.kind, row.viz_slot, row.sort = label, kind, viz_slot, sort
        else:
            session.add(Category(key=key, label=label, kind=kind, viz_slot=viz_slot, sort=sort))
    session.commit()
