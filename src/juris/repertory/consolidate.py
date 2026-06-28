"""Consolidate a legacy repertory DB into the canonical one.

The preflight warns when ``data/repertory.db`` (legacy) sits alongside the
canonical ``~/.juris/repertory.db``: a real-source run could read the stale one.
This merges the legacy ``chunks`` into the canonical (dedup by ``chunk_id``) so
the corpus lives in one place — read-additive, never destructive.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from juris.repertory.readiness import LEGACY_REPERTORY_PATH, resolve_repertory_path


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    """Outcome of a consolidation run."""

    merged: int  # chunks copied from legacy into canonical
    skipped: int  # legacy chunks already present (deduped)
    canonical: Path
    legacy: Path
    copied_whole: bool = False  # canonical didn't exist; legacy copied wholesale


def _count_chunks(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    finally:
        conn.close()


def consolidate_repertory(
    *, legacy: Path | None = None, canonical: Path | None = None
) -> ConsolidationResult:
    """Merge the legacy repertory DB into the canonical one (dedup by chunk_id)."""
    legacy = legacy or LEGACY_REPERTORY_PATH
    canonical = canonical or resolve_repertory_path()

    if not legacy.exists():
        return ConsolidationResult(merged=0, skipped=0, canonical=canonical, legacy=legacy)

    canonical.parent.mkdir(parents=True, exist_ok=True)
    if not canonical.exists():
        shutil.copy2(legacy, canonical)
        return ConsolidationResult(
            merged=_count_chunks(canonical),
            skipped=0,
            canonical=canonical,
            legacy=legacy,
            copied_whole=True,
        )

    src = sqlite3.connect(legacy)
    try:
        cursor = src.execute("SELECT * FROM chunks")
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
    finally:
        src.close()

    placeholders = ", ".join("?" for _ in columns)
    # Column names come from the legacy DB's own schema (cursor.description),
    # never user input — values are still parameterised.
    insert = f"INSERT OR IGNORE INTO chunks ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608

    dst = sqlite3.connect(canonical)
    try:
        before = int(dst.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        dst.executemany(insert, rows)
        dst.commit()
        after = int(dst.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    finally:
        dst.close()

    merged = after - before
    return ConsolidationResult(
        merged=merged,
        skipped=len(rows) - merged,
        canonical=canonical,
        legacy=legacy,
    )
