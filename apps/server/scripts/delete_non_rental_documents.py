#!/usr/bin/env python3
"""One-off deletion of confirmed-non-rental documents — docs/phases/PHASE-13-
rental-history-and-safe-to-spend-fix.md item B.

Real, explicit user request: delete the `doc_type='other'` bucket (bank/
broker/energy/game-storefront noise Phase 12 reclassified but deliberately did
not delete). `insurance` and `mortgage_interest_cert` documents are NEVER
touched — a judgement call already made in the phase spec, not this script's
to relitigate.

This is a real, irreversible local deletion (DB rows + `tax-documents/`
folders). Back up the DB and copy `tax-documents/` before running this —
same discipline as every prior data-touching phase. Reports COUNTS ONLY
(never subjects/senders — docs/PRIVATE.md redaction scheme); the list of
removed folder paths is logged locally for recoverability but is not itself
sensitive (generic sender-derived slugs, no real figures/names).
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
from app.rental_document_cleanup import delete_non_rental_documents  # noqa: E402


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}")


def main() -> int:
    get_settings()
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        res = delete_non_rental_documents(session)
        log(
            f"cleanup: scanned={res.scanned} deleted={res.deleted} "
            f"skipped_had_ledger_rows={res.skipped_had_ledger_rows} "
            f"folders_removed={res.folders_removed} folders_missing={res.folders_missing}"
        )
        for path in res.removed_folders:
            log(f"  removed: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
