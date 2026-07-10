#!/usr/bin/env python3
"""Pulls Starling (and, from Phase 3, Trading 212) into SQLite. Run by the
com.kakeibo.sync LaunchAgent every 6 hours (docs/DEPLOYMENT.md §4), invoked
via the venv's python directly (never `/bin/sh` — gotcha 2, macOS per-app
folder permissions attach to the binary). Exits 0 with a `not_configured`
sync_runs row while `KAKEIBO_STARLING_PAT` is absent — safe to install
before real credentials exist (docs/PLAN.md §6 rule 7).

Standalone: run from anywhere, `python scripts/sync_providers.py`; paths and
settings are resolved the same way `app.main` resolves them (env / `.env` in
`apps/server/`), not the CWD. Also importable — `sync_starling()` itself
lives in `app.sync_service` and is exercised directly by the test suite
against respx fixtures, never a live call.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# .../Finances/apps/server/scripts/sync_providers.py
#   parents[1] = apps/server (put on sys.path so `import app...` resolves
#   the same way it does under uvicorn, regardless of CWD)
SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base, User, seed_categories  # noqa: E402
from app.seed_goals import seed_goals  # noqa: E402
from app.sync_service import sync_starling, sync_trading212  # noqa: E402


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}")


async def _run() -> int:
    settings = get_settings()

    # Tables are normally created by app.main's lifespan; a standalone script
    # invocation (e.g. before the API has ever booted) needs the same
    # guarantee — `create_all`/`seed_categories` are idempotent no-ops once
    # they've already run (docs/phases/PHASE-1-scaffold.md item 2).
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        seed_categories(session)

        # Kakeibo is effectively single-user (docs/DATA_MODEL.md §1) — the
        # scheduled script has no request/session to derive a user from, so
        # it syncs the one household user. No users yet (e.g. nobody has
        # logged in even once) means nothing to sync against — log and exit
        # clean rather than inventing a user.
        user = session.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            log("skip: no Kakeibo user exists yet (log in via the web app first)")
            return 0

        seed_goals(session, settings, user_id=user.id)

        exit_code = 0
        starling_run = await sync_starling(session, user.id, settings)
        log(f"starling: status={starling_run.status} new_rows={starling_run.new_rows} detail={starling_run.detail or '-'}")
        if starling_run.status not in ("ok", "not_configured"):
            exit_code = 1

        t212_run = await sync_trading212(session, user.id, settings)
        log(f"trading212: status={t212_run.status} new_rows={t212_run.new_rows} detail={t212_run.detail or '-'}")
        if t212_run.status not in ("ok", "not_configured"):
            exit_code = 1

        return exit_code


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
