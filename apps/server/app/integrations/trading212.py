"""Trading 212 read-only client — docs/API.md §2.

Exposes exactly one method: ``get_account_summary()``. **No generic
request-dispatch escape hatch and no HTTP verb beyond GET anywhere in this
file** — same review-blocker discipline as ``integrations/starling.py``
(docs/ARCHITECTURE.md §5.2). No orders, no pies, no history endpoints; T212's
write-capable API surface is never referenced here even in a comment with a
real path.

Money boundary: T212's summary payload is GBP *floats*
(``cash.availableToTrade``, ``totalValue``, ...). This module converts every
one of them to integer pence at the parse boundary (``round(x * 100)``,
docs/API.md §2 "Ingest") — nothing downstream of :meth:`get_account_summary`
ever sees a float.

Auth (⚠️ verify — docs/API.md §2, no live credentials exist yet): HTTP Basic
(``key:secret`` base64) is tried first per T212's current public-API docs; if
that 401s, one legacy bare-header retry is attempted (the brief's
``legacyApiKeyHeader``, seen in older docs) before giving up. Whichever
scheme the account actually accepts on the first real call should be noted
back into API.md §2 in the same commit that removes the ⚠️.

Rate limit: the brief's spec is 1 request / 5s on this endpoint
(docs/API.md §2). This client enforces that itself, at the instance level,
regardless of how often a caller invokes :meth:`get_account_summary` — and
honours ``x-ratelimit-reset`` on a 429 with one retry.
"""
from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

LIVE_BASE_URL = "https://live.trading212.com"
DEMO_BASE_URL = "https://demo.trading212.com"
SUMMARY_PATH = "/api/v0/equity/account/summary"

DEFAULT_MIN_INTERVAL_SECONDS = 5.0


class T212Error(Exception):
    """Base class for Trading 212 client failures."""


class NotConfigured(T212Error):
    """No API key/secret is set (docs/SECRETS.md). The caller (the sync
    engine) catches this and records a `not_configured` sync_runs row rather
    than crashing (docs/PLAN.md §6 rule 7)."""


class T212Unavailable(T212Error):
    """Network error, timeout, non-2xx response, or an exhausted 429 retry
    from Trading 212."""


def _to_minor(amount: float) -> int:
    """Float GBP -> integer pence, at the boundary, once
    (docs/ARCHITECTURE.md §6, docs/API.md §2 `round(x*100)`). The one and
    only place a T212 float is allowed to exist."""
    return round(amount * 100)


@dataclass
class T212AccountSummary:
    provider_account_id: str
    currency: str
    total_value_minor: int
    cash_available_minor: int
    cash_in_pies_minor: int
    cash_reserved_minor: int
    investments_current_value_minor: int
    investments_total_cost_minor: int
    investments_realized_pl_minor: int
    investments_unrealized_pl_minor: int
    raw: dict[str, Any] = field(repr=False)  # full payload -> balance_snapshots.detail_json


def _parse_summary(body: dict[str, Any]) -> T212AccountSummary:
    cash = body.get("cash", {})
    investments = body.get("investments", {})
    return T212AccountSummary(
        provider_account_id=str(body["id"]),
        currency=body.get("currency", "GBP"),
        total_value_minor=_to_minor(body["totalValue"]),
        cash_available_minor=_to_minor(cash.get("availableToTrade", 0.0)),
        cash_in_pies_minor=_to_minor(cash.get("inPies", 0.0)),
        cash_reserved_minor=_to_minor(cash.get("reservedForOrders", 0.0)),
        investments_current_value_minor=_to_minor(investments.get("currentValue", 0.0)),
        investments_total_cost_minor=_to_minor(investments.get("totalCost", 0.0)),
        investments_realized_pl_minor=_to_minor(investments.get("realizedProfitLoss", 0.0)),
        investments_unrealized_pl_minor=_to_minor(investments.get("unrealizedProfitLoss", 0.0)),
        raw=body,
    )


class T212Client:
    """Read-only Trading 212 v0 API client. One instance per sync run — the
    5s-per-call spacing is tracked on the instance, so a fresh client each
    sync run never inherits a stale "last call" clock from a previous run.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        env: str = "live",
        base_url: str | None = None,
        timeout: float = 10.0,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key or not api_secret:
            raise NotConfigured("KAKEIBO_T212_API_KEY / KAKEIBO_T212_API_SECRET are not set")
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = (base_url or (LIVE_BASE_URL if env == "live" else DEMO_BASE_URL)).rstrip("/")
        self._timeout = timeout
        self._min_interval = min_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._last_call_at: float | None = None

    def _basic_headers(self) -> dict[str, str]:
        token = base64.b64encode(f"{self._api_key}:{self._api_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}", "Accept": "application/json"}

    def _legacy_headers(self) -> dict[str, str]:
        return {"Authorization": self._api_key, "Accept": "application/json"}

    async def _respect_rate_limit(self) -> None:
        """Sleeps just enough that this call starts >= min_interval after
        the previous one — enforced regardless of caller behaviour, per
        docs/API.md §2's "the client still sleeps 5s between any two T212
        calls"."""
        now = self._clock()
        if self._last_call_at is not None:
            wait = self._min_interval - (now - self._last_call_at)
            if wait > 0:
                await self._sleep(wait)
        self._last_call_at = self._clock()

    async def _get(self, path: str, headers: dict[str, str]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                return await client.get(path, headers=headers)
        except httpx.TimeoutException as exc:
            raise T212Unavailable(f"Trading 212 timed out calling {path}") from exc
        except httpx.HTTPError as exc:
            raise T212Unavailable(f"Trading 212 unreachable calling {path}: {exc}") from exc

    async def _request_with_auth_fallback(self, path: str) -> dict[str, Any]:
        """Basic auth first; one legacy bare-header retry only on a 401
        (docs/API.md §2 ⚠️ verify). A 429 is retried once, honouring
        ``x-ratelimit-reset``, at either auth stage."""
        response = await self._get_with_429_retry(path, self._basic_headers())
        if response.status_code == 401:
            response = await self._get_with_429_retry(path, self._legacy_headers())

        if response.status_code >= 400:
            raise T212Unavailable(
                f"Trading 212 {response.status_code} calling {path}: {response.text[:200]}"
            )
        return response.json()

    async def _get_with_429_retry(self, path: str, headers: dict[str, str]) -> httpx.Response:
        response = await self._get(path, headers)
        if response.status_code == 429:
            reset_header = response.headers.get("x-ratelimit-reset")
            try:
                wait = float(reset_header) if reset_header else self._min_interval
            except ValueError:
                wait = self._min_interval
            await self._sleep(max(wait, 0.0))
            response = await self._get(path, headers)
        return response

    async def get_account_summary(self) -> T212AccountSummary:
        """GET /api/v0/equity/account/summary (docs/API.md §2) — the *only*
        Trading 212 endpoint this app ever calls."""
        await self._respect_rate_limit()
        body = await self._request_with_auth_fallback(SUMMARY_PATH)
        return _parse_summary(body)
