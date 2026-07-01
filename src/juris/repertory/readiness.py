"""Repertory readiness — corpus presence, sufficiency, and canonical path.

This module is the single source of truth for two questions:

1. *Where does the repertory live?* — `resolve_repertory_path()` enforces a
   canonical location (`${JURIS_HOME:-~/.juris}/repertory.db`) with one
   allowed direct override (`JURIS_REPERTORY_PATH`). It also detects a legacy
   path (`data/repertory.db`) left behind by older command code so the operator
   can migrate manually — we never move, copy, or rewrite a corpus DB silently.

2. *Is the corpus usable for a real, lawyer-facing run?* — `read_status()`
   inspects the SQLite `chunks` table and returns a `RepertoryStatus` with
   chunk count, source count, per-`TipoFonte` breakdown, and a `is_ready`
   gate. Defaults: at least 100 chunks across 2 distinct source types.
   Both thresholds are configurable via env vars so the operator can tune
   without code changes once the partner-firm corpus shape is known.

The thresholds are operational guardrails, not legal-quality scores. They
only answer: *would running `juris demo --source datajud` here produce a
draft with verifiable citations, or would it silently fall back to an empty
retrieval?*
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from juris.core.paths import juris_home

UNKNOWN_SOURCE_TYPE: str = "(unknown)"
"""Sentinel for chunks whose ``source_type`` column is NULL.

We surface it in ``source_type_breakdown`` so operators can spot bad
ingestion metadata, but we exclude it from ``source_type_count`` — a
real corpus must show real diversity for the readiness gate to flip
to ready.
"""

CANONICAL_REPERTORY_PATH: Path = Path.home() / ".juris" / "repertory.db"
"""Legacy static canonical location for the repertory DB.

New code should call `resolve_repertory_path()` so `JURIS_HOME` is honored at
runtime. This constant is kept for compatibility with older imports.
"""

LEGACY_REPERTORY_PATH: Path = Path("data/repertory.db")
"""Legacy project-relative path used by `demo` and `draft` before Sprint 16.

Existence here triggers a warning so the operator can decide whether to
re-ingest at the canonical path or set `JURIS_REPERTORY_PATH` to keep using
this one. Migration is manual on purpose: corpus DBs are large and silent
moves are a documented anti-pattern for legal-critical state.
"""

DEFAULT_MIN_CHUNKS: int = 100
"""Default minimum chunk count for a real-source demo to be allowed."""

DEFAULT_MIN_SOURCE_TYPES: int = 2
"""Default minimum number of distinct `TipoFonte` tiers covered by chunks."""

ENV_REPERTORY_PATH: str = "JURIS_REPERTORY_PATH"
ENV_MIN_CHUNKS: str = "JURIS_MIN_REPERTORY_CHUNKS"
ENV_MIN_SOURCE_TYPES: str = "JURIS_MIN_REPERTORY_SOURCE_TYPES"


def default_repertory_path() -> Path:
    """Default repertory DB path under the configured Juris local state root."""
    return juris_home() / "repertory.db"


@dataclass(frozen=True, slots=True)
class RepertoryStatus:
    """Snapshot of corpus readiness for a single `repertory.db` file.

    Args:
        db_path: Resolved path inspected.
        exists: True if the file is present on disk.
        chunk_count: Total rows in the `chunks` table (0 if missing).
        source_count: Distinct `source_id` count (≈ ingested documents).
        source_type_breakdown: Map of `source_type` (TipoFonte string) to
            chunk count for that type. Empty when DB is missing or empty.
        min_chunks: Threshold used for the `is_ready` decision.
        min_source_types: Threshold used for the `is_ready` decision.
    """

    db_path: Path
    exists: bool
    chunk_count: int
    source_count: int
    source_type_breakdown: dict[str, int] = field(default_factory=dict)
    min_chunks: int = DEFAULT_MIN_CHUNKS
    min_source_types: int = DEFAULT_MIN_SOURCE_TYPES

    @property
    def source_type_count(self) -> int:
        """Distinct *real* `source_type` values present in chunks.

        Excludes the `(unknown)` sentinel for NULL columns so a corpus
        of "one real tier + a pile of NULL rows" cannot satisfy the
        diversity threshold. The sentinel stays visible in
        `source_type_breakdown` so operators can diagnose bad
        ingestion metadata.
        """
        return sum(
            1
            for name in self.source_type_breakdown
            if name != UNKNOWN_SOURCE_TYPE
        )

    @property
    def is_ready(self) -> bool:
        """True iff the corpus meets both thresholds for a real-source run."""
        return (
            self.exists
            and self.chunk_count >= self.min_chunks
            and self.source_type_count >= self.min_source_types
        )

    @property
    def not_ready_reason(self) -> str | None:
        """Operator-readable reason `is_ready` is False; None if ready."""
        if not self.exists:
            return f"banco não encontrado em {self.db_path}"
        if self.chunk_count == 0:
            return f"banco vazio em {self.db_path}"
        if self.chunk_count < self.min_chunks:
            return (
                f"chunks insuficientes ({self.chunk_count} < {self.min_chunks})"
            )
        if self.source_type_count < self.min_source_types:
            return (
                f"poucos tipos de fonte ({self.source_type_count} < "
                f"{self.min_source_types})"
            )
        return None

    def to_dict(self) -> dict[str, object]:
        """Serializable form for `--json` CLI output."""
        return {
            "db_path": str(self.db_path),
            "exists": self.exists,
            "chunk_count": self.chunk_count,
            "source_count": self.source_count,
            "source_type_count": self.source_type_count,
            "source_type_breakdown": dict(self.source_type_breakdown),
            "thresholds": {
                "min_chunks": self.min_chunks,
                "min_source_types": self.min_source_types,
            },
            "is_ready": self.is_ready,
            "not_ready_reason": self.not_ready_reason,
        }


def _env_int(name: str, default: int) -> int:
    """Read a non-negative int from env or fall back to default."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def resolve_repertory_path(override: Path | None = None) -> Path:
    """Resolve which repertory DB to use.

    Priority: explicit `override` arg > `JURIS_REPERTORY_PATH` env >
    `${JURIS_HOME:-~/.juris}/repertory.db`.
    """
    if override is not None:
        return override
    env = os.environ.get(ENV_REPERTORY_PATH)
    if env:
        return Path(env).expanduser()
    return default_repertory_path()


def detect_legacy_path(canonical: Path | None = None) -> Path | None:
    """Return resolved legacy path if a non-canonical DB exists, else None.

    A non-empty DB at `data/repertory.db` is a strong signal of older
    workflow state. Callers should warn the operator (never auto-move).
    """
    resolved_canonical = (canonical or resolve_repertory_path()).expanduser()
    legacy = LEGACY_REPERTORY_PATH.expanduser()
    if not legacy.exists():
        return None
    try:
        same = resolved_canonical.resolve() == legacy.resolve()
    except OSError:
        same = str(resolved_canonical) == str(legacy)
    if same:
        return None
    return legacy.resolve()


def read_status(
    path: Path | None = None,
    *,
    min_chunks: int | None = None,
    min_source_types: int | None = None,
) -> RepertoryStatus:
    """Inspect a repertory DB and return a readiness snapshot.

    Read-only — never creates or migrates the file. Defaults to the canonical
    path; pass `path` to inspect a specific DB without touching env state.

    Thresholds: explicit args > `JURIS_MIN_REPERTORY_*` env > module defaults.
    """
    db_path = resolve_repertory_path(path)
    mc = (
        min_chunks
        if min_chunks is not None
        else _env_int(ENV_MIN_CHUNKS, DEFAULT_MIN_CHUNKS)
    )
    mst = (
        min_source_types
        if min_source_types is not None
        else _env_int(ENV_MIN_SOURCE_TYPES, DEFAULT_MIN_SOURCE_TYPES)
    )

    if not db_path.exists():
        return RepertoryStatus(
            db_path=db_path,
            exists=False,
            chunk_count=0,
            source_count=0,
            min_chunks=mc,
            min_source_types=mst,
        )

    # Open read-only via URI to guarantee we never create the file or its
    # tables on inspection — a critical safety property of this gate.
    # Use ``Path.as_uri()`` so paths containing ``?`` / ``#`` / spaces are
    # percent-encoded; raw f-string interpolation breaks URI parsing on
    # those characters and silently misreports counts as zero.
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='chunks'"
        )
        if cursor.fetchone() is None:
            return RepertoryStatus(
                db_path=db_path,
                exists=True,
                chunk_count=0,
                source_count=0,
                min_chunks=mc,
                min_source_types=mst,
            )
        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT source_id) FROM chunks"
        )
        row = cursor.fetchone()
        chunk_count = int(row[0] or 0)
        source_count = int(row[1] or 0)
        cursor.execute(
            "SELECT COALESCE(source_type, '(unknown)'), COUNT(*) "
            "FROM chunks GROUP BY source_type"
        )
        breakdown = {str(name): int(count) for name, count in cursor.fetchall()}
    finally:
        conn.close()

    return RepertoryStatus(
        db_path=db_path,
        exists=True,
        chunk_count=chunk_count,
        source_count=source_count,
        source_type_breakdown=breakdown,
        min_chunks=mc,
        min_source_types=mst,
    )
