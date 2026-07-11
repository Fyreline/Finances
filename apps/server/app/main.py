"""Kakeibo FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --port 8201 --reload    # dev, kakeibo.dev.db
Production (LaunchAgent, Phase 8) runs port 8200 against kakeibo.db with
no --reload (docs/ARCHITECTURE.md §1).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import engine
from .deals_service import import_newest_deal_run
from .engines.deals import DealRunValidationError
from .errors import register_error_handlers
from .identity import MishkaIdentityClient
from .models import Base, seed_categories
from .routers import (
    accounts,
    auth,
    deals,
    gifts,
    goals,
    health,
    recurring,
    service,
    summary,
    sync,
    tax,
    transactions,
    wants,
)
from .seed_deals import seed_deals
from .seed_goals import seed_goals
from .tax_years import seed_tax_years

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.identity = MishkaIdentityClient(settings.mishka_base_url)
    # SQLite; tables created on startup (docs/ARCHITECTURE.md §4 — Alembic
    # only if a breaking change ever demands it).
    Base.metadata.create_all(engine)
    from .db import SessionLocal

    with SessionLocal() as session:
        seed_categories(session)
        # Tax years (docs/DATA_MODEL.md §6) — idempotent, same as categories.
        seed_tax_years(session)
        # Goal seeding needs a user to attach rows to and is a no-op until
        # one exists (nobody has logged in yet) — safe to call on every
        # startup, same as seed_categories (docs/phases/PHASE-3-t212-goals.md
        # item 4).
        seed_goals(session, settings)
        # Deals (docs/phases/PHASE-6-deals-splits.md item 3): write the one
        # synthetic placeholder file if data/deals/ is empty (never overwrites
        # a real run), then import whatever the newest file is — same
        # idempotent-per-file contract POST /api/deals/import uses. A
        # malformed hand-edited file must never crash boot, so this is the
        # one seed step allowed to log-and-continue instead of raising.
        # Skipped under the test environment deliberately: unlike the DB
        # (isolated per test run via KAKEIBO_DATABASE_URL, docs/tests/conftest.py),
        # data/deals/ has no per-run isolation knob, and this is the only seed
        # step that touches the filesystem — running it here would write a
        # real file into the repo's data/deals/ on every `pytest` invocation
        # and then re-import it into every test's fresh DB forever after.
        # deals-router tests exercise seed_deals()/import_newest_deal_run()
        # directly instead (test_seed_deals.py, test_deals_router.py).
        if settings.environment != "test":
            seed_deals(deals.DEALS_DIR)
            try:
                import_newest_deal_run(session, deals.DEALS_DIR)
            except DealRunValidationError as exc:
                logger.warning("lifespan: newest data/deals/*.json failed validation, skipped: %s", exc)
    logger.info("lifespan: tables ensured, categories seeded, Mishka base url = %s", settings.mishka_base_url)
    yield


def create_app() -> FastAPI:
    app_settings = get_settings()
    app = FastAPI(title="Kakeibo", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    # /api/health and /api/auth/(login|refresh|logout) stay public;
    # /api/auth/me and /api/auth/settings enforce auth themselves via
    # Depends(current_user). Session-required on literally everything else
    # once later phases add routers (docs/AUTH.md §3).
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(transactions.router, prefix="/api")
    app.include_router(sync.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(goals.router, prefix="/api")
    # /api/goal/service authenticates itself with the static sibling token
    # (routers/service.py) — machine-to-machine, outside the JWT flow.
    app.include_router(service.router, prefix="/api")
    app.include_router(tax.router, prefix="/api")
    app.include_router(summary.router, prefix="/api")
    app.include_router(recurring.router, prefix="/api")
    app.include_router(deals.router, prefix="/api")
    app.include_router(gifts.router, prefix="/api")
    app.include_router(wants.router, prefix="/api")

    return app


app = create_app()
