"""app/integrations/trading212.py — respx-stubbed against
tests/fixtures/trading212/ (no live calls, docs/phases/PHASE-3-t212-goals.md
item 1: "Fixture-tested"). Also the money-boundary proof (no float leaves
this module) and the rate-limit/auth-fallback behaviour docs/API.md §2
specifies.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.integrations.trading212 import DEMO_BASE_URL, LIVE_BASE_URL, NotConfigured, T212Client, T212Unavailable

FIXTURES = Path(__file__).parent / "fixtures" / "trading212"
BASE = LIVE_BASE_URL
SUMMARY_URL = f"{BASE}/api/v0/equity/account/summary"


def _fixture() -> dict:
    return json.loads((FIXTURES / "account_summary.json").read_text())


def test_not_configured_when_key_or_secret_empty():
    with pytest.raises(NotConfigured):
        T212Client("", "")
    with pytest.raises(NotConfigured):
        T212Client("key-only", "")
    with pytest.raises(NotConfigured):
        T212Client("", "secret-only")


def test_demo_env_uses_demo_base_url():
    client = T212Client("key", "secret", env="demo")
    assert client._base_url == DEMO_BASE_URL  # noqa: SLF001 — whitebox check, no public getter needed


@pytest.mark.anyio
@respx.mock
async def test_get_account_summary_uses_basic_auth_first():
    route = respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=_fixture()))
    client = T212Client("my-key", "my-secret")
    await client.get_account_summary()

    sent = route.calls.last.request.headers["Authorization"]
    expected = "Basic " + base64.b64encode(b"my-key:my-secret").decode()
    assert sent == expected


@pytest.mark.anyio
@respx.mock
async def test_get_account_summary_parses_fields_no_floats():
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=_fixture()))
    client = T212Client("key", "secret")
    summary = await client.get_account_summary()

    assert summary.provider_account_id == "555000111"
    assert summary.currency == "GBP"
    assert summary.total_value_minor == 42400
    assert summary.cash_available_minor == 12345
    assert summary.cash_in_pies_minor == 5000
    assert summary.cash_reserved_minor == 0
    assert summary.investments_current_value_minor == 30055
    assert summary.investments_total_cost_minor == 29000
    assert summary.investments_realized_pl_minor == 1000
    assert summary.investments_unrealized_pl_minor == 1055

    for field_name in (
        "total_value_minor",
        "cash_available_minor",
        "cash_in_pies_minor",
        "cash_reserved_minor",
        "investments_current_value_minor",
        "investments_total_cost_minor",
        "investments_realized_pl_minor",
        "investments_unrealized_pl_minor",
    ):
        value = getattr(summary, field_name)
        assert isinstance(value, int), f"{field_name} must be an int, never a float"


@pytest.mark.anyio
@respx.mock
async def test_get_account_summary_rounds_half_pence_case():
    """docs/phases/PHASE-3-t212-goals.md acceptance: "test on a .005
    rounding case" — proves the client uses exactly `round(x * 100)`
    (docs/API.md §2's stated convention) with no separate/inconsistent
    rounding elsewhere. Python's round() is round-half-to-even: 424.005
    lands on 42400.5 in float64 and rounds to the even neighbour, 42400."""
    body = _fixture()
    body["totalValue"] = 424.005
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=body))
    client = T212Client("key", "secret")
    summary = await client.get_account_summary()
    assert summary.total_value_minor == round(424.005 * 100)
    assert summary.total_value_minor == 42400
    assert isinstance(summary.total_value_minor, int)


@pytest.mark.anyio
@respx.mock
async def test_falls_back_to_legacy_header_on_401():
    """docs/API.md §2 ⚠️ verify: Basic first, legacy bare-header retry only
    if the call 401s."""
    route = respx.get(SUMMARY_URL)
    route.side_effect = [
        httpx.Response(401, text="unauthorized"),
        httpx.Response(200, json=_fixture()),
    ]
    client = T212Client("legacy-key", "unused-secret")
    summary = await client.get_account_summary()

    assert summary.total_value_minor == 42400
    assert route.call_count == 2
    first_auth = route.calls[0].request.headers["Authorization"]
    second_auth = route.calls[1].request.headers["Authorization"]
    assert first_auth.startswith("Basic ")
    assert second_auth == "legacy-key", "the legacy scheme sends the bare key, no Basic/base64"


@pytest.mark.anyio
@respx.mock
async def test_raises_unavailable_when_both_auth_schemes_fail():
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    client = T212Client("key", "secret")
    with pytest.raises(T212Unavailable):
        await client.get_account_summary()


@pytest.mark.anyio
@respx.mock
async def test_raises_unavailable_on_server_error():
    respx.get(SUMMARY_URL).mock(return_value=httpx.Response(500, text="internal error"))
    client = T212Client("key", "secret")
    with pytest.raises(T212Unavailable):
        await client.get_account_summary()


@pytest.mark.anyio
@respx.mock
async def test_raises_unavailable_on_connection_error():
    respx.get(SUMMARY_URL).mock(side_effect=httpx.ConnectError("refused"))
    client = T212Client("key", "secret")
    with pytest.raises(T212Unavailable):
        await client.get_account_summary()


@pytest.mark.anyio
@respx.mock
async def test_429_honours_ratelimit_reset_header_and_retries_once():
    route = respx.get(SUMMARY_URL)
    route.side_effect = [
        httpx.Response(429, headers={"x-ratelimit-reset": "7"}, text="slow down"),
        httpx.Response(200, json=_fixture()),
    ]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = T212Client("key", "secret", sleep=fake_sleep)
    summary = await client.get_account_summary()

    assert summary.total_value_minor == 42400
    assert route.call_count == 2
    # First sleep is the 429's x-ratelimit-reset wait (there's no prior call
    # yet, so the plain rate-limit spacer doesn't also fire).
    assert 7.0 in sleeps


@pytest.mark.anyio
async def test_rate_limit_enforces_five_second_spacing_between_calls():
    """docs/phases/PHASE-3-t212-goals.md acceptance: "two forced calls are
    >=5s apart (client-level, mocked clock)" — a fake clock/sleep pair so
    the test runs instantly while still proving the client computed and
    awaited the correct wait duration."""
    fake_now = [1_000.0]
    sleeps: list[float] = []

    def fake_clock() -> float:
        return fake_now[0]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now[0] += seconds

    with respx.mock:
        respx.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=_fixture()))
        client = T212Client("key", "secret", clock=fake_clock, sleep=fake_sleep)

        await client.get_account_summary()
        assert sleeps == [], "no prior call yet, nothing to space out against"

        fake_now[0] += 1.0  # only 1s has "passed" before the second call
        await client.get_account_summary()

    assert sleeps == [4.0], "needed 4 more seconds to reach the 5s minimum spacing"


def test_no_write_verbs_in_trading212_client():
    """docs/ARCHITECTURE.md §5.2 acceptance grep, enforced in-process too."""
    import app.integrations.trading212 as mod

    source = Path(mod.__file__).read_text()
    for verb in (".post(", ".put(", ".delete(", ".patch("):
        assert verb not in source, f"found a write verb {verb!r} in trading212.py"
