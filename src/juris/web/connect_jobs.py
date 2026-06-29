"""Durable connect-job store — survives restart, tenant-scoped (ADR-0015 Phase 2).

The connect import/sync runs in the background and can take minutes. An in-memory
dict loses every job on a restart/deploy — unacceptable for a multi-tenant SaaS. A
small SQLite table persists each job (status, result, error, owner tenant) so a
poll after a restart still finds it, and ownership can be checked on read.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / ".juris" / "connect_jobs.db"


class ConnectJobStore:
    """SQLite-backed store for ``/api/connect`` background jobs."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connect_jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at REAL NOT NULL
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def create(self, job_id: str, tenant_id: str) -> None:
        """Record a new job as ``running`` (monotonic created_at for FIFO eviction)."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO connect_jobs "
                "(job_id, tenant_id, status, result_json, error, created_at) "
                "VALUES (?, ?, 'running', NULL, NULL, ?)",
                (job_id, tenant_id, time.monotonic()),
            )

    def mark_done(self, job_id: str, result: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE connect_jobs SET status='done', result_json=? WHERE job_id=?",
                (json.dumps(result), job_id),
            )

    def mark_error(self, job_id: str, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE connect_jobs SET status='error', error=? WHERE job_id=?",
                (error, job_id),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the job (status/result/error/tenant_id) or None — caller checks owner."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT tenant_id, status, result_json, error FROM connect_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        tenant_id, status, result_json, error = row
        return {
            "tenant_id": tenant_id,
            "status": status,
            "result": json.loads(result_json) if result_json else None,
            "error": error,
        }

    def evict_old(self, max_jobs: int = 200) -> None:
        """Drop the oldest jobs beyond ``max_jobs`` (FIFO) so the table stays bounded."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM connect_jobs WHERE job_id IN ("
                "  SELECT job_id FROM connect_jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?"
                ")",
                (max_jobs,),
            )
