"""Application settings, loaded from environment / .env file.

All settings are prefixed with KAKEIBO_ (docs/ARCHITECTURE.md §4). Kakeibo's
secret and settings are entirely independent of Mishka Hub's and Michi's own
— the three apps share nothing but the identity verification call
(docs/AUTH.md).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../Finances/apps/server/app/config.py
#   parents[1] = apps/server (the backend dir, where .env lives)
#   parents[3] = Finances (the project root, where data/ lives)
SERVER_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SERVER_DIR / ".env"),
        env_prefix="KAKEIBO_",
        extra="ignore",
    )

    environment: str = "development"

    # --- Auth (docs/AUTH.md). 32+ random bytes,
    # e.g. python3 -c "import secrets; print(secrets.token_urlsafe(48))".
    # Independent of MISHKA_JWT_SECRET and MICHI_JWT_SECRET — rotating one
    # never affects either sibling's sessions. Access tokens stay at 15
    # minutes deliberately (AUTH.md §3) — do not be tempted upward. ---
    jwt_secret: str = ""
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # --- The one call Kakeibo makes to Mishka Hub: verifying a login
    # (docs/AUTH.md §2). Loopback by default; identity.py refuses a plain
    # http non-loopback URL at startup. ---
    mishka_base_url: str = "http://127.0.0.1:8000"

    # --- CORS. Kakeibo's web dev server owns port 5178 (Mishka's owns 5173,
    # Michi's 5174, Japan_website's 5175-5177 — docs/ARCHITECTURE.md §1; the
    # dev port moved from an originally-assigned 5175 after a collision with
    # Japan_website was discovered post-Phase-1, docs/HANDOFF.md "Port
    # conflict — resolved"). This default drifted out of sync with that fix
    # (still read 5175) until Phase 2 caught and corrected it. ---
    cors_origins: list[str] = [
        "http://localhost:5178",
        "http://127.0.0.1:5178",
        "https://fyreline.github.io",
    ]

    # SQLite lives in the project-level data/ folder (CWD-independent
    # absolute path). Prod serves kakeibo.db; the dev launch.json entry
    # overrides this to kakeibo.dev.db (docs/ARCHITECTURE.md §1 — the
    # dev/prod split lesson paid for twice on Michi).
    database_url: str = f"sqlite:///{DATA_DIR / 'kakeibo.db'}"

    # --- Integration credential slots (docs/SECRETS.md). None exist yet;
    # every integration degrades to "not_configured" rather than crash
    # (PLAN.md §6 rule 7) — absence of a value IS the not-configured state,
    # there is no separate enabled/disabled flag. ---
    starling_pat: str = ""
    # Optional floor date (YYYY-MM-DD) for a first-ever backfill — e.g. "only
    # pull from when the rental era / house-share era started, not the whole
    # account history". Deliberately NOT hardcoded anywhere (docs/PRIVATE.md's
    # redaction scheme: no real dates in committed source) — absent, the
    # first sync simply backfills from each account's own `createdAt`
    # (docs/API.md §1c). Set locally in `.env` (gitignored) if wanted.
    starling_backfill_start: str = ""
    t212_api_key: str = ""
    t212_api_secret: str = ""
    t212_env: str = "live"
    gmail_credentials_path: str = "data/secrets/client_secret.json"
    gmail_token_path: str = "data/secrets/gmail-token.json"
    # Comma-separated known rental-paperwork senders (letting agent, lender,
    # insurer, HMRC/accountant) — the Gmail query is built from these plus the
    # subject keywords (docs/API.md §3c). Empty until HANDOFF Q3 is answered, in
    # which case the pull no-ops with a `not_configured` row rather than
    # scanning the whole mailbox on subject keywords alone. Real addresses live
    # only in a local gitignored `.env` (docs/PRIVATE.md redaction scheme).
    gmail_senders: str = ""
    gmail_search_days: int = 400

    # --- Goal seeding (docs/phases/PHASE-3-t212-goals.md item 4, docs/
    # PRIVATE.md's redaction scheme). These are personal-finance *values*,
    # not secrets — ARCHITECTURE.md §4's "config lives in DB, not env" rule
    # is about ongoing user-editable settings (payday, salary, ...), which
    # already have PATCH endpoints; a goal's target/baseline currently only
    # has a one-time bootstrap path, so this mirrors the
    # KAKEIBO_STARLING_BACKFILL_START precedent instead: optional, empty by
    # default, real values live only in a local gitignored `.env`, never
    # committed here or seeded into migration/seed code as a literal. Absent
    # -> the goal simply isn't created yet (its bubble stays in setup state).
    # Stored as strings (not int) so "unset" is unambiguously "" rather than
    # a fake 0 baseline. ---
    goal_house_deposit_target_minor: str = ""
    goal_house_deposit_target_date: str = ""
    goal_house_deposit_baseline_minor: str = ""
    goal_house_deposit_baseline_date: str = ""
    goal_t212_rebuild_baseline_minor: str = ""
    goal_t212_rebuild_baseline_date: str = ""

    @property
    def auth_configured(self) -> bool:
        return bool(self.jwt_secret)

    @property
    def starling_configured(self) -> bool:
        return bool(self.starling_pat)

    @property
    def t212_configured(self) -> bool:
        return bool(self.t212_api_key and self.t212_api_secret)

    @property
    def gmail_configured(self) -> bool:
        return Path(self.gmail_token_path).exists()


@lru_cache
def get_settings() -> Settings:
    return Settings()
