"""Starling Bank read-only client — docs/API.md §1.

Exposes exactly four methods: ``get_accounts / get_balance / get_feed /
get_spaces``. **No generic request-dispatch escape hatch and no HTTP verb
beyond GET anywhere in this file** — this is a review-blocker per
docs/ARCHITECTURE.md §5.2 (the phase-2 acceptance grep for the other three
mutating verbs against this file must return nothing). Starling's own
payment/write endpoints are never referenced, scaffolded, or imported here,
even in a comment with a real path — that scope simply does not exist in
this client's vocabulary.

Money boundary: Starling already speaks integer ``minorUnits`` — this module
combines that with ``direction`` (``IN``/``OUT``) into a single signed
``amount_minor`` int (negative = out, docs/ARCHITECTURE.md §6) at parse time,
immediately, so nothing downstream ever sees an unsigned amount + direction
pair or a float. No float touches money anywhere in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.starlingbank.com"


class StarlingError(Exception):
    """Base class for Starling client failures."""


class NotConfigured(StarlingError):
    """No Personal Access Token is set — docs/SECRETS.md. The caller (the
    sync engine) catches this and records a `not_configured` sync_runs row
    rather than crashing (docs/PLAN.md §6 rule 7)."""


class StarlingUnavailable(StarlingError):
    """Network error, timeout, or non-2xx response from Starling."""


def _signed_minor(amount: dict[str, Any], direction: str) -> int:
    """`{currency, minorUnits}` + `IN`/`OUT` -> one signed int, at the
    boundary, once (docs/ARCHITECTURE.md §6)."""
    minor_units = int(amount["minorUnits"])
    return minor_units if direction == "IN" else -minor_units


@dataclass
class StarlingAccount:
    account_uid: str
    default_category_uid: str
    currency: str
    created_at: str  # ISO-8601 UTC, as returned
    name: str


@dataclass
class StarlingBalance:
    cleared_minor: int
    effective_minor: int
    currency: str


@dataclass
class StarlingFeedItem:
    feed_item_uid: str
    category_uid: str
    amount_minor: int  # signed — already converted (never raw minorUnits+direction downstream)
    direction: str  # "IN" | "OUT" — kept for reference/debugging only
    transaction_time: str  # ISO-8601 UTC
    settlement_time: str | None
    status: str
    counter_party_name: str | None
    reference: str | None
    spending_category: str | None
    source: str | None
    raw: dict[str, Any] = field(repr=False)  # full payload -> transactions.raw_json


@dataclass
class StarlingSpace:
    space_uid: str
    name: str
    balance_minor: int


class StarlingClient:
    """Read-only Starling v2 API client. One instance per sync run.

    Raises :class:`NotConfigured` immediately if ``pat`` is falsy — callers
    should construct this right before use, inside the same try/except that
    handles the not-configured degrade path, rather than holding an instance
    around.
    """

    def __init__(self, pat: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0) -> None:
        if not pat:
            raise NotConfigured("KAKEIBO_STARLING_PAT is not set")
        self._pat = pat
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._pat}", "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.get(path, params=params, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise StarlingUnavailable(f"Starling timed out calling {path}") from exc
        except httpx.HTTPError as exc:
            raise StarlingUnavailable(f"Starling unreachable calling {path}: {exc}") from exc

        if response.status_code >= 400:
            raise StarlingUnavailable(
                f"Starling {response.status_code} calling {path}: {response.text[:200]}"
            )
        return response.json()

    async def get_accounts(self) -> list[StarlingAccount]:
        """GET /api/v2/accounts — one call at first sync; persists
        accountUid + defaultCategory (docs/API.md §1b)."""
        body = await self._get("/api/v2/accounts")
        return [
            StarlingAccount(
                account_uid=a["accountUid"],
                default_category_uid=a["defaultCategory"],
                currency=a["currency"],
                created_at=a["createdAt"],
                name=a["name"],
            )
            for a in body.get("accounts", [])
        ]

    async def get_balance(self, account_uid: str) -> StarlingBalance:
        """GET /api/v2/accounts/{accountUid}/balance."""
        body = await self._get(f"/api/v2/accounts/{account_uid}/balance")
        cleared = body["clearedBalance"]
        effective = body["effectiveBalance"]
        return StarlingBalance(
            cleared_minor=int(cleared["minorUnits"]),
            effective_minor=int(effective["minorUnits"]),
            currency=cleared["currency"],
        )

    async def get_feed(
        self, account_uid: str, category_uid: str, min_timestamp: str, max_timestamp: str
    ) -> list[StarlingFeedItem]:
        """GET .../feed/account/{accountUid}/category/{categoryUid}/transactions-between
        (docs/API.md §1b). Timestamps are ISO-8601 UTC strings, caller's job
        to format (docs/app/dates.py)."""
        body = await self._get(
            f"/api/v2/feed/account/{account_uid}/category/{category_uid}/transactions-between",
            params={"minTransactionTimestamp": min_timestamp, "maxTransactionTimestamp": max_timestamp},
        )
        items: list[StarlingFeedItem] = []
        for it in body.get("feedItems", []):
            direction = it["direction"]
            items.append(
                StarlingFeedItem(
                    feed_item_uid=it["feedItemUid"],
                    category_uid=it["categoryUid"],
                    amount_minor=_signed_minor(it["amount"], direction),
                    direction=direction,
                    transaction_time=it["transactionTime"],
                    settlement_time=it.get("settlementTime"),
                    status=it.get("status", "UNKNOWN"),
                    counter_party_name=it.get("counterPartyName"),
                    reference=it.get("reference"),
                    spending_category=it.get("spendingCategory"),
                    source=it.get("source"),
                    raw=it,
                )
            )
        return items

    async def get_spaces(self, account_uid: str) -> list[StarlingSpace]:
        """GET /api/v2/account/{accountUid}/savings-goals — Starling's
        "Spaces" in the app UI are the savings-goals API under the hood
        (docs/API.md §1b, corrected at Phase 2 implementation time from an
        earlier `.../spaces` guess). Method name kept as `get_spaces` per
        docs/phases/PHASE-2-starling.md's acceptance list."""
        body = await self._get(f"/api/v2/account/{account_uid}/savings-goals")
        spaces: list[StarlingSpace] = []
        for g in body.get("savingsGoalList", body.get("savingsGoals", [])):
            total = g.get("totalSaved") or g.get("savedAmount") or {"minorUnits": 0}
            spaces.append(
                StarlingSpace(
                    space_uid=g.get("savingsGoalUid", g.get("uid", "")),
                    name=g.get("name", ""),
                    balance_minor=int(total["minorUnits"]),
                )
            )
        return spaces
