"""Per-user JWT auth guard.

Every router except ``/api/health`` and the login/refresh/logout endpoints in
``routers/auth.py`` requires a valid ``Authorization: Bearer <access token>``
JWT, verified here — session-required on literally everything else
(docs/AUTH.md §3). Port of the siblings' ``app/auth.py``.
"""
from __future__ import annotations

from fastapi import Request

from .errors import KakeiboHTTPException
from .security import TokenError, decode_access_token


def current_user(request: Request) -> int:
    """Verify the bearer JWT and return the authenticated user's id.

    Also sets ``request.state.user_id`` so downstream handlers can read it
    without re-decoding the token.
    """
    settings = request.app.state.settings

    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise KakeiboHTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
            code="unauthorized",
        )

    token = header.removeprefix("Bearer ").strip()
    try:
        user_id = decode_access_token(token, settings)
    except TokenError as exc:
        raise KakeiboHTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
            code="unauthorized",
        ) from exc

    request.state.user_id = user_id
    return user_id
