"""app/integrations/starling.py — respx-stubbed against the fixtures in
tests/fixtures/starling/ (docs/phases/PHASE-2-starling.md item 2: "no live
calls in tests"). Also the money-boundary proof: Starling's
`{minorUnits} + direction` becomes one signed int and nothing downstream
ever sees a float or an unsigned amount (docs/ARCHITECTURE.md §6).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.integrations.starling import NotConfigured, StarlingClient, StarlingUnavailable

FIXTURES = Path(__file__).parent / "fixtures" / "starling"
BASE = "https://api.starlingbank.com"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_not_configured_when_pat_empty():
    with pytest.raises(NotConfigured):
        StarlingClient("")


@pytest.mark.anyio
@respx.mock
async def test_get_accounts_parses_fields():
    respx.get(f"{BASE}/api/v2/accounts").mock(return_value=httpx.Response(200, json=_fixture("accounts.json")))
    client = StarlingClient("fake-pat", base_url=BASE)
    accounts = await client.get_accounts()
    assert len(accounts) == 1
    acc = accounts[0]
    assert acc.account_uid == "acc-0001-primary"
    assert acc.default_category_uid == "cat-0001-default"
    assert acc.currency == "GBP"
    assert acc.name == "Personal"


@pytest.mark.anyio
@respx.mock
async def test_get_accounts_sends_bearer_auth():
    route = respx.get(f"{BASE}/api/v2/accounts").mock(
        return_value=httpx.Response(200, json=_fixture("accounts.json"))
    )
    client = StarlingClient("secret-pat-value", base_url=BASE)
    await client.get_accounts()
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-pat-value"


@pytest.mark.anyio
@respx.mock
async def test_get_balance_no_floats_signed_correctly():
    respx.get(f"{BASE}/api/v2/accounts/acc-0001-primary/balance").mock(
        return_value=httpx.Response(200, json=_fixture("balance.json"))
    )
    client = StarlingClient("fake-pat", base_url=BASE)
    balance = await client.get_balance("acc-0001-primary")
    assert balance.cleared_minor == 123456
    assert balance.effective_minor == 120000
    assert isinstance(balance.cleared_minor, int)
    assert isinstance(balance.effective_minor, int)


@pytest.mark.anyio
@respx.mock
async def test_get_feed_signs_amount_by_direction():
    respx.get(f"{BASE}/api/v2/feed/account/acc-0001-primary/category/cat-0001-default/transactions-between").mock(
        return_value=httpx.Response(200, json=_fixture("feed.json"))
    )
    client = StarlingClient("fake-pat", base_url=BASE)
    items = await client.get_feed(
        "acc-0001-primary", "cat-0001-default", "2026-05-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"
    )
    assert len(items) == 5

    grocery = next(i for i in items if i.feed_item_uid == "feed-0001")
    assert grocery.amount_minor == -4599, "OUT direction must be negative pence"
    assert isinstance(grocery.amount_minor, int)
    assert grocery.spending_category == "GROCERIES"
    assert grocery.counter_party_name == "Willow & Pine Grocers"

    salary = next(i for i in items if i.feed_item_uid == "feed-0003")
    assert salary.amount_minor == 250000, "IN direction must be positive pence"

    pending = next(i for i in items if i.feed_item_uid == "feed-0004")
    assert pending.status == "PENDING"
    assert pending.settlement_time is None


@pytest.mark.anyio
@respx.mock
async def test_get_feed_query_params_forwarded():
    route = respx.get(
        f"{BASE}/api/v2/feed/account/acc-0001-primary/category/cat-0001-default/transactions-between"
    ).mock(return_value=httpx.Response(200, json={"feedItems": []}))
    client = StarlingClient("fake-pat", base_url=BASE)
    await client.get_feed(
        "acc-0001-primary", "cat-0001-default", "2026-05-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"
    )
    request = route.calls.last.request
    assert "minTransactionTimestamp=2026-05-01" in str(request.url)
    assert "maxTransactionTimestamp=2026-06-01" in str(request.url)


@pytest.mark.anyio
@respx.mock
async def test_get_spaces_uses_savings_goals_endpoint():
    """docs/API.md §1b: Starling's "Spaces" are the savings-goals API
    under the hood — corrected at Phase 2 implementation time from an
    earlier `.../spaces` guess."""
    respx.get(f"{BASE}/api/v2/account/acc-0001-primary/savings-goals").mock(
        return_value=httpx.Response(200, json=_fixture("savings_goals.json"))
    )
    client = StarlingClient("fake-pat", base_url=BASE)
    spaces = await client.get_spaces("acc-0001-primary")
    assert len(spaces) == 1
    assert spaces[0].space_uid == "goal-0001"
    assert spaces[0].name == "Rainy day"
    assert spaces[0].balance_minor == 30000


@pytest.mark.anyio
@respx.mock
async def test_starling_error_status_raises_unavailable():
    respx.get(f"{BASE}/api/v2/accounts").mock(return_value=httpx.Response(500, text="internal error"))
    client = StarlingClient("fake-pat", base_url=BASE)
    with pytest.raises(StarlingUnavailable):
        await client.get_accounts()


@pytest.mark.anyio
@respx.mock
async def test_starling_connection_error_raises_unavailable():
    respx.get(f"{BASE}/api/v2/accounts").mock(side_effect=httpx.ConnectError("refused"))
    client = StarlingClient("fake-pat", base_url=BASE)
    with pytest.raises(StarlingUnavailable):
        await client.get_accounts()


def test_no_write_verbs_in_starling_client():
    """docs/ARCHITECTURE.md §5.2 acceptance grep, enforced in-process too:
    the client must expose no generic request() and call no HTTP verb but
    GET anywhere in the module source."""
    import app.integrations.starling as mod

    source = Path(mod.__file__).read_text()
    for verb in (".post(", ".put(", ".delete(", ".patch("):
        assert verb not in source, f"found a write verb {verb!r} in starling.py"
