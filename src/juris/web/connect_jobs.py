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

from juris.core.paths import ensure_private_dir, juris_home, restrict_file


def default_connect_jobs_path() -> Path:
    """Default durable job DB path, aligned with the web app's ``JURIS_HOME``."""
    return juris_home() / "connect_jobs.db"


class ConnectJobStore:
    """SQLite-backed store for ``/api/connect`` background jobs."""

    def __init__(self, db_path: Path | None = None) -> None:
        uses_default_path = db_path is None
        self._path = db_path or default_connect_jobs_path()
        ensure_private_dir(self._path.parent, restrict_existing=uses_default_path)
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
        if self._path.exists():
            restrict_file(self._path)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def create(self, job_id: str, tenant_id: str) -> None:
        """Record a new job as ``running``.

        ``created_at`` is the UTC epoch (``time.time()``) — stable across restarts,
        unlike a monotonic clock, so FIFO eviction stays correct after a reboot.
        """
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO connect_jobs "
                "(job_id, tenant_id, status, result_json, error, created_at) "
                "VALUES (?, ?, 'running', NULL, NULL, ?)",
                (job_id, tenant_id, time.time()),
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

    def sweep_stale(self, max_age_seconds: float) -> int:
        """Mark ``running`` jobs older than ``max_age_seconds`` as ``error``.

        Run at startup: a job whose worker died (crash/restart) would otherwise stay
        ``running`` forever. Returns the number of rows swept.
        """
        cutoff = time.time() - max_age_seconds
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE connect_jobs SET status='error', "
                "error='interrompido (reinício do servidor)' "
                "WHERE status='running' AND created_at < ?",
                (cutoff,),
            )
            return int(cur.rowcount)

    def evict_old(self, max_jobs: int = 200, *, tenant_id: str | None = None) -> None:
        """Drop the oldest jobs beyond ``max_jobs`` (FIFO) so the table stays bounded.

        When ``tenant_id`` is provided, eviction is scoped to that tenant. A busy
        tenant should not erase another firm's recent connect history.
        """
        with self._conn() as conn:
            if tenant_id is None:
                conn.execute(
                    "DELETE FROM connect_jobs WHERE job_id IN ("
                    "  SELECT job_id FROM connect_jobs "
                    "  ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?"  # rowid breaks epoch ties
                    ")",
                    (max_jobs,),
                )
                return
            conn.execute(
                "DELETE FROM connect_jobs WHERE job_id IN ("
                "  SELECT job_id FROM connect_jobs WHERE tenant_id = ? "
                "  ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET ?"  # rowid breaks epoch ties
                ")",
                (tenant_id, max_jobs),
            )
