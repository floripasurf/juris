"""LGPD/pilot data erasure operations.

The pilot terms promise that client data held by Juris can be deleted after the
pilot. This module turns that promise into an operator-run workflow with a
dry-run plan, explicit confirmation, scoped deletion, and a non-PII erasure
certificate.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from juris.core.paths import ensure_private_dir, juris_home, restrict_file
from juris.repertory.readiness import resolve_repertory_path
from juris.web.auth import PUBLIC_TENANT_ID, Tenant, tenant_scoped_dir, validate_tenant_id
from juris.web.connect_jobs import default_connect_jobs_path

ERASURE_LOG_NAME = "compliance-erasure.jsonl"


@dataclass(frozen=True, slots=True)
class ErasureTarget:
    """Filesystem target planned for erasure."""

    path: Path
    kind: str
    exists: bool
    file_count: int
    total_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "exists": self.exists,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True, slots=True)
class TenantErasurePlan:
    """Dry-run plan for deleting one tenant's client data."""

    tenant_id: str
    created_at: str
    targets: tuple[ErasureTarget, ...]
    connect_jobs: int
    corpus_chunks: int
    erasure_log_path: Path
    confirmation_phrase: str
    warnings: tuple[str, ...]

    @property
    def file_count(self) -> int:
        return sum(target.file_count for target in self.targets)

    @property
    def total_bytes(self) -> int:
        return sum(target.total_bytes for target in self.targets)

    def to_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "created_at": self.created_at,
            "targets": [target.to_dict() for target in self.targets],
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "connect_jobs": self.connect_jobs,
            "corpus_chunks": self.corpus_chunks,
            "erasure_log_path": str(self.erasure_log_path),
            "confirmation_phrase": self.confirmation_phrase,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class TenantErasureResult:
    """Result of an executed tenant erasure."""

    tenant_id: str
    targets_deleted: int
    files_deleted: int
    bytes_deleted: int
    connect_jobs_deleted: int
    corpus_chunks_deleted: int
    erasure_log_path: Path
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "targets_deleted": self.targets_deleted,
            "files_deleted": self.files_deleted,
            "bytes_deleted": self.bytes_deleted,
            "connect_jobs_deleted": self.connect_jobs_deleted,
            "corpus_chunks_deleted": self.corpus_chunks_deleted,
            "erasure_log_path": str(self.erasure_log_path),
            "warnings": list(self.warnings),
        }


def build_tenant_erasure_plan(
    tenant_id: str,
    *,
    juris_home_path: Path | None = None,
    out_root: Path | None = None,
    repertory_path: Path | None = None,
    connect_jobs_path: Path | None = None,
    allow_public: bool = False,
) -> TenantErasurePlan:
    """Build a dry-run plan for erasing one tenant's client data."""
    tid = validate_tenant_id(tenant_id)
    if tid == PUBLIC_TENANT_ID and not allow_public:
        msg = "deleção do tenant public exige allow_public=True"
        raise ValueError(msg)

    home = (juris_home_path or juris_home()).expanduser()
    out = (out_root or _default_out_root()).expanduser()
    corpus = resolve_repertory_path(repertory_path).expanduser()
    jobs = (connect_jobs_path or default_connect_jobs_path()).expanduser()
    warnings: list[str] = []

    target_paths = _target_paths_for_tenant(tid, home=home, out_root=out, warnings=warnings)
    targets = tuple(_describe_target(path) for path in target_paths)
    connect_count = _count_connect_jobs(jobs, tid)
    corpus_count = _count_tenant_corpus_chunks(corpus, tid)

    return TenantErasurePlan(
        tenant_id=tid,
        created_at=datetime.now(UTC).isoformat(),
        targets=targets,
        connect_jobs=connect_count,
        corpus_chunks=corpus_count,
        erasure_log_path=home / ERASURE_LOG_NAME,
        confirmation_phrase=f"ERASE-{tid}",
        warnings=tuple(warnings),
    )


def execute_tenant_erasure(
    plan: TenantErasurePlan,
    *,
    confirmation: str,
    juris_home_path: Path | None = None,
    out_root: Path | None = None,
    repertory_path: Path | None = None,
    connect_jobs_path: Path | None = None,
) -> TenantErasureResult:
    """Execute an erasure plan after exact confirmation."""
    if confirmation != plan.confirmation_phrase:
        msg = f"confirmação inválida; use {plan.confirmation_phrase!r}"
        raise ValueError(msg)

    home = (juris_home_path or juris_home()).expanduser()
    out = (out_root or _default_out_root()).expanduser()
    corpus = resolve_repertory_path(repertory_path).expanduser()
    jobs = (connect_jobs_path or default_connect_jobs_path()).expanduser()

    allowed_roots = _allowed_roots(plan.tenant_id, home=home, out_root=out)
    warnings = list(plan.warnings)
    deleted_targets = 0
    for target in plan.targets:
        if not target.exists:
            continue
        _assert_safe_delete_target(target.path, allowed_roots)
        _delete_path(target.path)
        deleted_targets += 1

    connect_deleted = _delete_connect_jobs(jobs, plan.tenant_id)
    corpus_deleted = _delete_tenant_corpus_chunks(corpus, plan.tenant_id)

    result = TenantErasureResult(
        tenant_id=plan.tenant_id,
        targets_deleted=deleted_targets,
        files_deleted=plan.file_count,
        bytes_deleted=plan.total_bytes,
        connect_jobs_deleted=connect_deleted,
        corpus_chunks_deleted=corpus_deleted,
        erasure_log_path=plan.erasure_log_path,
        warnings=tuple(warnings),
    )
    _append_erasure_certificate(result)
    return result


def _target_paths_for_tenant(tenant_id: str, *, home: Path, out_root: Path, warnings: list[str]) -> list[Path]:
    tenant = Tenant(tenant_id)
    if tenant_id != PUBLIC_TENANT_ID:
        return [
            tenant_scoped_dir(tenant, home),
            tenant_scoped_dir(tenant, out_root),
        ]

    # Public mode is legacy/single-user. Avoid deleting the storage root itself:
    # remove only known client-data artifacts and direct output entries, preserving
    # backups, configured tenant roots, and the erasure certificate location.
    targets = [
        home / "juris.db",
        home / "audit.jsonl",
        home / "audit.jsonl.anchor.json",
        home / "filings",
        home / "cache" / "datajud",
    ]
    if out_root.exists():
        for child in sorted(out_root.iterdir()):
            if child.name == "tenants":
                warnings.append(f"preserved configured tenant output root: {child}")
                continue
            targets.append(child)
    return targets


def _default_out_root() -> Path:
    return Path(os.environ.get("JURIS_OUT_ROOT", "juris-out"))


def _allowed_roots(tenant_id: str, *, home: Path, out_root: Path) -> tuple[Path, ...]:
    tenant = Tenant(tenant_id)
    if tenant_id != PUBLIC_TENANT_ID:
        return (
            tenant_scoped_dir(tenant, home).resolve(strict=False),
            tenant_scoped_dir(tenant, out_root).resolve(strict=False),
        )
    return (home.resolve(strict=False), out_root.resolve(strict=False))


def _describe_target(path: Path) -> ErasureTarget:
    expanded = path.expanduser()
    if not expanded.exists() and not expanded.is_symlink():
        return ErasureTarget(path=expanded, kind="missing", exists=False, file_count=0, total_bytes=0)
    if expanded.is_file() or expanded.is_symlink():
        return ErasureTarget(
            path=expanded,
            kind="file",
            exists=True,
            file_count=1,
            total_bytes=_lstat_size(expanded),
        )

    file_count = 0
    total_bytes = 0
    for child in expanded.rglob("*"):
        if child.is_dir() and not child.is_symlink():
            continue
        file_count += 1
        total_bytes += _lstat_size(child)
    return ErasureTarget(
        path=expanded,
        kind="directory",
        exists=True,
        file_count=file_count,
        total_bytes=total_bytes,
    )


def _lstat_size(path: Path) -> int:
    try:
        return int(path.lstat().st_size)
    except OSError:
        return 0


def _assert_safe_delete_target(path: Path, allowed_roots: tuple[Path, ...]) -> None:
    resolved = path.resolve(strict=False)
    if not any(resolved == root or _is_relative_to(resolved, root) for root in allowed_roots):
        msg = f"alvo de deleção fora das raízes permitidas: {path}"
        raise ValueError(msg)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _delete_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path)


def _count_connect_jobs(path: Path, tenant_id: str) -> int:
    return _connect_jobs_op(path, tenant_id, delete=False)


def _delete_connect_jobs(path: Path, tenant_id: str) -> int:
    return _connect_jobs_op(path, tenant_id, delete=True)


def _connect_jobs_op(path: Path, tenant_id: str, *, delete: bool) -> int:
    if not path.exists():
        return 0
    with sqlite3.connect(path) as conn:
        if not _table_exists(conn, "connect_jobs"):
            return 0
        if not delete:
            row = conn.execute("SELECT COUNT(*) FROM connect_jobs WHERE tenant_id = ?", (tenant_id,)).fetchone()
            return int(row[0] if row else 0)
        cur = conn.execute("DELETE FROM connect_jobs WHERE tenant_id = ?", (tenant_id,))
        return int(cur.rowcount)


def _count_tenant_corpus_chunks(path: Path, tenant_id: str) -> int:
    return _tenant_corpus_chunks_op(path, tenant_id, delete=False)


def _delete_tenant_corpus_chunks(path: Path, tenant_id: str) -> int:
    return _tenant_corpus_chunks_op(path, tenant_id, delete=True)


def _tenant_corpus_chunks_op(path: Path, tenant_id: str, *, delete: bool) -> int:
    if not path.exists():
        return 0
    with sqlite3.connect(path) as conn:
        if not _table_exists(conn, "chunks"):
            return 0
        if not _column_exists(conn, "chunks", "tenant_id"):
            return 0
        if not delete:
            row = conn.execute("SELECT COUNT(*) FROM chunks WHERE tenant_id = ?", (tenant_id,)).fetchone()
            return int(row[0] if row else 0)
        rowids = [row[0] for row in conn.execute("SELECT rowid FROM chunks WHERE tenant_id = ?", (tenant_id,))]
        if _table_exists(conn, "chunks_fts"):
            for rowid in rowids:
                conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (rowid,))
        conn.execute("DELETE FROM chunks WHERE tenant_id = ?", (tenant_id,))
        return len(rowids)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))  # noqa: S608


def _append_erasure_certificate(result: TenantErasureResult) -> None:
    ensure_private_dir(result.erasure_log_path.parent)
    record = {
        "event": "tenant.erasure",
        "created_at": datetime.now(UTC).isoformat(),
        **result.to_dict(),
    }
    with result.erasure_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    restrict_file(result.erasure_log_path)
