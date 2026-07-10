#!/usr/bin/env python3
"""Nightly snapshot of the production SQLite db (data/kakeibo.db — the real
household's money history) plus a weekly archive of tax-documents/ (real
paperwork, not re-derivable if the source Gmail messages are ever deleted).
Run by the com.kakeibo.backup LaunchAgent at 03:15 (docs/DEPLOYMENT.md §4 —
03:15, not 03:00, so it never contends with Michi's backup for disk). The
agent must invoke this via the venv's python — not /bin/sh, which macOS's
per-app folder permissions block from touching ~/Documents even though the
venv's python is already trusted (the Michi gotcha, pre-paid).

Uses sqlite3's own .backup() API, not a plain file copy — a copy of a
WAL-mode db mid-write can grab an inconsistent snapshot. Port of Michi's
scripts/backup_db.py with the tax-documents delta.

Standalone, stdlib-only. Run from anywhere; paths resolve relative to this
file, not the CWD.
"""
from __future__ import annotations

import sqlite3
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# .../Finances/apps/server/scripts/backup_db.py
#   parents[3] = Finances (project root, where data/ and tax-documents/ live)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB = PROJECT_ROOT / "data" / "kakeibo.db"
TAX_DOCUMENTS = PROJECT_ROOT / "tax-documents"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
KEEP_DB = 30  # nightly snapshots (docs/DEPLOYMENT.md §4)
KEEP_TAX = 8  # weekly tax-documents archives (~2 months)
TAX_ARCHIVE_EVERY = timedelta(days=7)


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {msg}")


def backup_db() -> None:
    if not DB.exists():
        log(f"skip db: nothing at {DB}")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"kakeibo-{stamp}.db"
    src_conn = sqlite3.connect(str(DB))
    dest_conn = sqlite3.connect(str(dest))
    with dest_conn:
        src_conn.backup(dest_conn)
    dest_conn.close()
    src_conn.close()
    log(f"backed up db to {dest}")
    snapshots = sorted(BACKUP_DIR.glob("kakeibo-*.db"), key=lambda p: p.name, reverse=True)
    for old in snapshots[KEEP_DB:]:
        old.unlink()
        log(f"pruned {old}")


def _has_content(root: Path) -> bool:
    return any(p.is_file() and p.name != ".gitkeep" for p in root.rglob("*"))


def backup_tax_documents() -> None:
    """Weekly tar.gz of tax-documents/ (docs/DEPLOYMENT.md §4). The agent
    runs nightly; this no-ops unless the newest archive is over a week old."""
    if not TAX_DOCUMENTS.exists() or not _has_content(TAX_DOCUMENTS):
        log("skip tax-documents: empty")
        return
    archives = sorted(BACKUP_DIR.glob("tax-documents-*.tar.gz"), key=lambda p: p.name, reverse=True)
    if archives:
        newest = archives[0].name.removeprefix("tax-documents-").removesuffix(".tar.gz")
        try:
            newest_at = datetime.strptime(newest, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - newest_at < TAX_ARCHIVE_EVERY:
                log(f"skip tax-documents: newest archive {archives[0].name} is under a week old")
                return
        except ValueError:
            pass  # unparseable name — archive anyway rather than silently never archiving
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"tax-documents-{stamp}.tar.gz"
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(TAX_DOCUMENTS, arcname="tax-documents")
    log(f"archived tax-documents to {dest}")
    archives = sorted(BACKUP_DIR.glob("tax-documents-*.tar.gz"), key=lambda p: p.name, reverse=True)
    for old in archives[KEEP_TAX:]:
        old.unlink()
        log(f"pruned {old}")


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_db()
    backup_tax_documents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
