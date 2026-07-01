"""Tests for repertory consolidation (legacy DB → canonical)."""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

from juris.repertory.consolidate import consolidate_repertory


def _seed(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT, "
        "source_type TEXT, text TEXT, metadata TEXT, position INTEGER DEFAULT 0)"
    )
    conn.executemany(
        "INSERT OR IGNORE INTO chunks (chunk_id, source_id, source_type, text) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    finally:
        conn.close()


def test_merges_legacy_into_canonical_deduping(tmp_path: Path) -> None:
    legacy = tmp_path / "data" / "repertory.db"
    canonical = tmp_path / ".juris" / "repertory.db"
    _seed(legacy, [("c1", "s1", "STF", "x"), ("c2", "s1", "STF", "y")])
    _seed(canonical, [("c2", "s1", "STF", "y"), ("c3", "s2", "STJ", "z")])  # c2 overlaps

    result = consolidate_repertory(legacy=legacy, canonical=canonical)

    assert result.merged == 1  # only c1 was new
    assert result.skipped == 1  # c2 already present
    assert _count(canonical) == 3  # c1 + c2 + c3
    assert stat.S_IMODE(canonical.stat().st_mode) == 0o600


def test_copies_when_canonical_missing(tmp_path: Path) -> None:
    legacy = tmp_path / "data" / "repertory.db"
    canonical = tmp_path / ".juris" / "repertory.db"  # does not exist yet
    _seed(legacy, [("c1", "s1", "STF", "x"), ("c2", "s1", "STF", "y")])

    result = consolidate_repertory(legacy=legacy, canonical=canonical)

    assert result.merged == 2
    assert canonical.exists()
    assert _count(canonical) == 2
    assert stat.S_IMODE(canonical.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(canonical.stat().st_mode) == 0o600


def test_noop_when_legacy_missing(tmp_path: Path) -> None:
    canonical = tmp_path / ".juris" / "repertory.db"
    _seed(canonical, [("c1", "s1", "STF", "x")])

    result = consolidate_repertory(legacy=tmp_path / "nope.db", canonical=canonical)

    assert result.merged == 0
    assert result.skipped == 0
