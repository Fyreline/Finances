"""engines/deals.py — pure parsing/staleness logic (docs/API.md §4,
docs/phases/PHASE-6-deals-splits.md acceptance list). No I/O beyond reading a
file the test itself writes to a tmp_path.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.engines.deals import (
    DealRunValidationError,
    is_stale,
    load_deal_run_file,
    newest_deal_run_file,
    parse_run_at,
    validate_deal_run,
)

VALID_PAYLOAD = {
    "run_at": "2026-07-13T09:00:00Z",
    "method": "agent_research",
    "sources": [{"url": "https://example.com/rates", "fetched_at": "2026-07-13T09:00:00Z"}],
    "deals": [
        {
            "provider": "Example BS",
            "product": "Easy Access",
            "aer_pct": 4.6,
            "access": "easy",
            "min_deposit_minor": 0,
            "fscs": True,
            "is_isa": False,
            "source_url": "https://example.com/rates",
            "notes": "includes a bonus",
        }
    ],
}


def test_parse_run_at_handles_trailing_z():
    dt = parse_run_at("2026-07-13T09:00:00Z")
    assert dt.year == 2026 and dt.tzinfo is not None


def test_validate_deal_run_accepts_the_documented_shape():
    validate_deal_run(VALID_PAYLOAD)  # no raise


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("run_at"),
        lambda p: p.pop("method"),
        lambda p: p.__setitem__("sources", []),
        lambda p: p["sources"][0].pop("url"),
        lambda p: p["sources"][0].pop("fetched_at"),
        lambda p: p.__setitem__("deals", []),
        lambda p: p["deals"][0].pop("provider"),
        lambda p: p["deals"][0].pop("source_url"),
        lambda p: p["deals"][0].__setitem__("source_url", ""),
    ],
)
def test_validate_deal_run_rejects_missing_required_fields(mutate):
    payload = json.loads(json.dumps(VALID_PAYLOAD))  # deep copy
    mutate(payload)
    with pytest.raises(DealRunValidationError):
        validate_deal_run(payload)


def test_load_deal_run_file_validates(tmp_path):
    good = tmp_path / "2026-07-13.json"
    good.write_text(json.dumps(VALID_PAYLOAD))
    payload = load_deal_run_file(good)
    assert payload["deals"][0]["provider"] == "Example BS"

    bad_payload = json.loads(json.dumps(VALID_PAYLOAD))
    bad_payload["deals"][0].pop("source_url")
    bad = tmp_path / "2026-07-14.json"
    bad.write_text(json.dumps(bad_payload))
    with pytest.raises(DealRunValidationError):
        load_deal_run_file(bad)


def test_newest_deal_run_file_picks_lexicographically_last(tmp_path):
    (tmp_path / "2026-05-01.json").write_text("{}")
    (tmp_path / "2026-07-13.json").write_text("{}")
    (tmp_path / "2026-06-10.json").write_text("{}")
    newest = newest_deal_run_file(tmp_path)
    assert newest is not None
    assert newest.name == "2026-07-13.json"


def test_newest_deal_run_file_none_when_empty(tmp_path):
    assert newest_deal_run_file(tmp_path) is None


def test_is_stale_true_past_35_days_forged_clock():
    """Clock-forged test (docs/phases/PHASE-6 acceptance): a run dated 40 days
    before an explicit `now` is stale, without touching the real clock."""
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    run_at = now - timedelta(days=40)
    assert is_stale(run_at, now=now) is True


def test_is_stale_false_within_35_days_forged_clock():
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    run_at = now - timedelta(days=10)
    assert is_stale(run_at, now=now) is False


def test_is_stale_boundary_exactly_35_days_is_not_yet_stale():
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    run_at = now - timedelta(days=35)
    assert is_stale(run_at, now=now) is False
