"""app/seed_deals.py — docs/phases/PHASE-6-deals-splits.md item 3, the
code-seed design decision recorded in seed_deals.py's own module docstring
(docs/PLAN.md §6 rule 1). No I/O beyond a tmp_path.
"""
from __future__ import annotations

import json

from app.seed_deals import seed_deals


def test_seed_deals_writes_one_synthetic_file_into_an_empty_dir(tmp_path):
    deals_dir = tmp_path / "deals"
    written = seed_deals(deals_dir)

    assert written is not None
    assert written.parent == deals_dir
    payload = json.loads(written.read_text())
    assert payload["method"] == "manual"
    assert len(payload["deals"]) == 1
    deal = payload["deals"][0]
    # Unambiguously fake — never a plausible-looking real rate/provider
    # (docs/PLAN.md's hard constraint on this phase).
    assert "SYNTHETIC" in deal["notes"]
    assert "SYNTHETIC" in deal["provider"] or "synthetic" in deal["provider"].lower()
    assert deal["source_url"].endswith(".invalid/synthetic-fixture")


def test_seed_deals_never_overwrites_an_existing_run(tmp_path):
    deals_dir = tmp_path / "deals"
    deals_dir.mkdir(parents=True)
    real_run = deals_dir / "2026-07-13.json"
    real_run.write_text('{"already": "here"}')

    written = seed_deals(deals_dir)

    assert written is None
    assert real_run.read_text() == '{"already": "here"}'
    assert list(deals_dir.glob("*.json")) == [real_run]
