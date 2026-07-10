#!/usr/bin/env python3
"""Pull rental paperwork from Gmail into tax-documents/ — docs/API.md §3c.

Run by the com.kakeibo.gmail LaunchAgent weekly (docs/DEPLOYMENT.md §4),
invoked via the venv's python directly. Exits 0 with a ``not_configured``
gmail sync_runs row while Gmail isn't authorised yet or no sender is configured
(HANDOFF Q3) — safe to install before credentials exist (docs/PLAN.md §6 rule
7). Standalone + importable: the pull logic lives in ``app.gmail_pull`` and is
exercised directly by the test suite against a fake Gmail service, never a live
Google call.

Per HANDOFF Q2 (the statutory-deadline question): once real OAuth is connected,
this pull is also how Kakeibo cross-checks whether the right tax year's rental
income was declared — it pulls HMRC Self Assessment correspondence, accountant
emails, and rent-received notices for a human to review on the TaxPage.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.gmail_pull import pull_rental_emails  # noqa: E402
from app.models import Base, TaxConfig, User, seed_categories  # noqa: E402
from app.tax_years import seed_tax_years  # noqa: E402


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}")


def main() -> int:
    settings = get_settings()
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        seed_categories(session)
        seed_tax_years(session)

        user = session.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            log("skip: no Kakeibo user exists yet (log in via the web app first)")
            return 0

        cfg = session.get(TaxConfig, user.id)
        letting_agent = cfg.letting_agent if cfg else None

        run = pull_rental_emails(session, settings, letting_agent=letting_agent)
        log(f"gmail: status={run.status} new_documents={run.new_rows} detail={run.detail or '-'}")
        return 0 if run.status in ("ok", "not_configured") else 1


if __name__ == "__main__":
    sys.exit(main())
