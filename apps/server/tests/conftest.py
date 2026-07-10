"""Shared pytest fixtures.

Sets test-only env vars (isolated sqlite file, a throwaway JWT secret) BEFORE
anything imports the ``app`` package, since app/config.py + app/db.py read
settings at import time. No pytest-asyncio needed: FastAPI's own dependency
(starlette) pulls in anyio, which registers its own pytest plugin, so plain
``@pytest.mark.anyio`` works for testing async code directly (e.g.
identity.py) without an extra dev dependency.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="kakeibo-test-"))
os.environ.setdefault("KAKEIBO_JWT_SECRET", "test-secret-not-for-production-use-only")
os.environ.setdefault("KAKEIBO_DATABASE_URL", f"sqlite:///{_TEST_DATA_DIR / 'kakeibo-test.db'}")
os.environ.setdefault("KAKEIBO_MISHKA_BASE_URL", "http://127.0.0.1:8000")
os.environ.setdefault("KAKEIBO_ENVIRONMENT", "test")
# gmail_configured does a real Path.exists() check (not a truthiness check
# like starling/t212), so — unlike those two — env_file=None alone doesn't
# isolate it: a real gmail-token.json on the developer's actual filesystem
# would still be "found" via config.py's PROJECT_ROOT-anchored resolution.
# Point both at a location inside the isolated test tmpdir, which never has
# a real token, mirroring the KAKEIBO_DATABASE_URL isolation above (bug
# found 2026-07-11 the moment a real token first existed on disk).
os.environ.setdefault("KAKEIBO_GMAIL_CREDENTIALS_PATH", str(_TEST_DATA_DIR / "no-such-client-secret.json"))
os.environ.setdefault("KAKEIBO_GMAIL_TOKEN_PATH", str(_TEST_DATA_DIR / "no-such-gmail-token.json"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.routers import auth as auth_module  # noqa: E402
from app.routers import health as health_module  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _clean_state():
    """Fresh tables, a reset health-reachability cache, and a reset login
    rate-limit deque for every test — all three are module-level state that
    would otherwise leak between tests."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    health_module._cache["checked_at"] = 0.0
    health_module._cache["reachable"] = False
    auth_module._login_failures.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_user(email: str = "mack@example.com", display_name: str = "Mack", mishka_id: int = 1) -> int:
    """Insert a Kakeibo user row directly (bypassing the Mishka login proxy)
    and return its id — for exercising authed endpoints without standing up
    a fake identity server."""
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        user = User(
            email=email.lower(),
            display_name=display_name,
            mishka_user_id=mishka_id,
            created_at="2026-07-01 00:00:00",
            settings_json="{}",
        )
        db.add(user)
        db.commit()
        return user.id


def auth_headers(user_id: int) -> dict[str, str]:
    from app.config import get_settings
    from app.security import create_access_token

    token = create_access_token(user_id, get_settings())
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def authed(client):
    """(client, user_id, headers) for a freshly-inserted household user."""
    user_id = make_user()
    return client, user_id, auth_headers(user_id)
