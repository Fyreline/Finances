"""Pure functions behind the Deals bubble/DealsPage (docs/API.md §4,
docs/DESIGN.md §4h, docs/DATA_MODEL.md §7).

**This module never fetches anything.** The savings-deals feature is
deliberately humble about a real constraint (no dependable free UK
savings-rate API — API.md §4): a *human or a scheduled Claude agent* does the
actual research and writes a dated, source-cited ``data/deals/<date>.json``
file (schema below); everything here just understands that on-disk shape —
parsing it, and deciding whether a run is stale. ``deals_service.py`` owns
turning a parsed file into ``deal_runs``/``savings_deals`` rows;
``routers/deals.py`` owns the HTTP surface.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# docs/DESIGN.md §4h / docs/API.md §4: "a run older than 35 days renders a
# 'these rates are from <date> — likely stale' banner."
STALE_AFTER_DAYS = 35

# docs/phases/PHASE-6-deals-splits.md acceptance: "Every rendered deal has a
# working source link and a date; no deal without both can exist
# (schema-enforced NOT NULL, import rejects violations)." The date comes from
# the shared deal_run.run_at (every deal in a file shares one research-run
# date); source_url is per-deal.
REQUIRED_DEAL_FIELDS = ("provider", "product", "aer_pct", "access", "source_url")


class DealRunValidationError(ValueError):
    """A ``data/deals/*.json`` file is missing a required field. Import must
    refuse the whole file rather than partially import it — a deal without a
    source or a date must never be able to exist in the database."""


def parse_run_at(raw: str) -> datetime:
    """Parse the ISO8601 ``run_at`` timestamp (docs/API.md §4 example uses a
    trailing ``Z``, which ``datetime.fromisoformat`` only accepts once
    normalised to ``+00:00``)."""
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def is_stale(run_at: datetime, now: datetime | None = None) -> bool:
    """True once a research run is more than ``STALE_AFTER_DAYS`` old. Takes
    an explicit ``now`` (default: real UTC now) so tests can forge either side
    of the clock without patching global time — pass a ``now`` far enough
    ahead of a fixture's ``run_at``, or a ``run_at`` far enough behind the
    real now, whichever reads more naturally for the test."""
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - run_at).days > STALE_AFTER_DAYS


def validate_deal_run(payload: dict) -> None:
    """Raise ``DealRunValidationError`` if the file violates the schema's
    NOT NULL discipline (docs/API.md §4). Called before anything is written
    to the database."""
    if not payload.get("run_at"):
        raise DealRunValidationError("run_at is required")
    try:
        parse_run_at(payload["run_at"])
    except (ValueError, TypeError) as exc:
        raise DealRunValidationError(f"run_at is not a valid ISO8601 timestamp: {exc}") from exc
    if not payload.get("method"):
        raise DealRunValidationError("method is required")

    sources = payload.get("sources") or []
    if not sources:
        raise DealRunValidationError("a research run needs at least one source")
    for source in sources:
        if not source.get("url") or not source.get("fetched_at"):
            raise DealRunValidationError("every source needs a url and a fetched_at date")

    deals = payload.get("deals") or []
    if not deals:
        raise DealRunValidationError("a research run needs at least one deal")
    for deal in deals:
        for field in REQUIRED_DEAL_FIELDS:
            if deal.get(field) in (None, ""):
                raise DealRunValidationError(f"deal is missing required field: {field}")


def load_deal_run_file(path: Path) -> dict:
    """Read + validate one research-run JSON file. Raises
    ``DealRunValidationError`` (schema violation) or ``json.JSONDecodeError``
    (not valid JSON at all) — both are the caller's cue to refuse the import."""
    payload = json.loads(path.read_text())
    validate_deal_run(payload)
    return payload


def newest_deal_run_file(deals_dir: Path) -> Path | None:
    """The lexicographically-last ``*.json`` file in ``data/deals/`` —
    filenames are ``YYYY-MM-DD.json``, so lexicographic order is chronological
    order (docs/phases/PHASE-6 acceptance: "newest run wins the display")."""
    files = sorted(deals_dir.glob("*.json"))
    return files[-1] if files else None
