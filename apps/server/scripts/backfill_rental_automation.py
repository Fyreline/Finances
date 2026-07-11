#!/usr/bin/env python3
"""One-off backfill for Phase 12 rental-statement automation — docs/phases/
PHASE-12-rental-automation.md items 1a + 1d, extended docs/phases/PHASE-13-
rental-history-and-safe-to-spend-fix.md item C.

Runs two idempotent, safe-to-re-run data fixes against the local database and
reports COUNTS ONLY (never subjects/amounts — docs/PRIVATE.md redaction scheme):

  1. reclassify the review queue — move keyword-false-positive `rent_statement`
     documents (bank/energy/broker "statement" emails) to `other`;
  2. backfill the ledger — parse each confirmed letting-agent statement PDF and
     create its income + expense rows, fixing the `gross_rents_minor: 0` estimate.
     Now also re-parses documents ledgered by an earlier run and additively adds
     a `repairs` row for any Property Costs Summary deduction that wasn't
     captured then (item C) — see `already_ledgered` vs `topped_up` in the log.

Same category of scripted migration as Phase 10's tax_config field-setting. The
sender domain used to confirm statements comes from
`KAKEIBO_RENT_STATEMENT_SENDER_DOMAIN` (local `.env`, gitignored) — absent, the
subject-prefix gate alone is used (which already matches the real statements).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.rental_backfill import backfill_rental_ledger, reclassify_misfiled_rent_statements  # noqa: E402


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}")


def main() -> int:
    settings = get_settings()
    Base.metadata.create_all(engine)
    agent_domain = getattr(settings, "rent_statement_sender_domain", "") or None

    with SessionLocal() as session:
        rc = reclassify_misfiled_rent_statements(session, agent_domain=agent_domain)
        log(f"reclassify: scanned={rc['scanned']} reclassified_to_other={rc['reclassified']} kept_as_rent_statement={rc['kept']}")

        bf = backfill_rental_ledger(session, agent_domain=agent_domain)
        log(
            f"backfill: confirmed_statements={bf['confirmed_statements']} "
            f"ledgered_now={bf['ledgered_now']} already_ledgered={bf['already_ledgered']} "
            f"topped_up={bf['topped_up']} "
            f"ledger_rows_created={bf['ledger_rows_created']} outcomes={bf['outcomes']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
