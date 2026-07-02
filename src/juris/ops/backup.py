"""Operational backup/restore for local Juris state.

The backup format is intentionally simple: a gzipped tarball with a
``manifest.json`` plus only relative archive paths. Restore extracts only files
listed in the manifest and confines every target path under the requested
restore directory.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, cast

from juris import __version__
from juris.core.paths import ensure_private_dir, juris_home, restrict_file
from juris.repertory.readiness import resolve_repertory_path

BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Result of a completed backup operation."""

    archive_path: Path
    checksum_path: Path
    archive_sha256: str
    file_count: int
    total_bytes: int
    warnings: tuple[str, ...]
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Result of a restore operation."""

    target_root: Path
    files_restored: tuple[Path, ...]
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class _CollectedFile:
    source_path: Path
    archive_path: str
    group: str


def default_backup_dir() -> Path:
    """Default destination for operational backup archives."""
    return Path(os.environ.get("JURIS_BACKUP_DIR", str(juris_home() / "backups"))).expanduser()


def default_out_root() -> Path:
    """Default root for generated case artifacts."""
    return Path(os.environ.get("JURIS_OUT_ROOT", "juris-out")).expanduser()


def create_backup(
    *,
    output: Path | None = None,
    juris_home_path: Path | None = None,
    out_root: Path | None = None,
    repertory_path: Path | None = None,
    include_out_root: bool = True,
) -> BackupResult:
    """Create a backup tarball with critical local Juris artifacts.

    Included roots:
    - ``JURIS_HOME``: audit chain, tenant SQLite DBs, filing receipts, queues.
    - ``JURIS_OUT_ROOT``: generated case artifacts, when ``include_out_root``.
    - ``JURIS_REPERTORY_PATH``/canonical repertory DB, when outside ``JURIS_HOME``.
    """
    archive_path = _resolve_archive_output(output)
    ensure_private_dir(archive_path.parent)

    home = (juris_home_path or juris_home()).expanduser()
    resolved_out = (out_root or default_out_root()).expanduser()
    corpus = resolve_repertory_path(repertory_path).expanduser()

    warnings: list[str] = []
    excluded_roots = _excluded_backup_roots(archive_path)
    files = _collect_backup_files(
        home,
        out_root=resolved_out,
        repertory_path=corpus,
        include_out_root=include_out_root,
        excluded_roots=excluded_roots,
        warnings=warnings,
    )

    items: list[dict[str, object]] = []
    total_bytes = 0
    for item in files:
        size = item.source_path.stat().st_size
        total_bytes += size
        items.append(
            {
                "archive_path": item.archive_path,
                "source_path": str(item.source_path),
                "group": item.group,
                "sha256": _sha256_file(item.source_path),
                "size_bytes": size,
            }
        )

    created_at = datetime.now(UTC).isoformat()
    manifest: dict[str, object] = {
        "format": "juris-operational-backup",
        "version": BACKUP_FORMAT_VERSION,
        "created_at": created_at,
        "juris_version": __version__,
        "roots": {
            "juris_home": str(home),
            "out_root": str(resolved_out) if include_out_root else None,
            "repertory_path": str(corpus),
        },
        "file_count": len(items),
        "total_bytes": total_bytes,
        "items": items,
        "warnings": warnings,
    }

    _write_backup_archive(archive_path, files, manifest)
    restrict_file(archive_path)

    archive_sha = _sha256_file(archive_path)
    checksum_path = Path(f"{archive_path}.sha256")
    checksum_path.write_text(f"{archive_sha}  {archive_path.name}\n", encoding="utf-8")
    restrict_file(checksum_path)

    return BackupResult(
        archive_path=archive_path,
        checksum_path=checksum_path,
        archive_sha256=archive_sha,
        file_count=len(items),
        total_bytes=total_bytes,
        warnings=tuple(warnings),
        manifest=manifest,
    )


def restore_backup(
    archive_path: Path,
    *,
    target_root: Path,
    overwrite: bool = False,
) -> RestoreResult:
    """Restore a Juris backup under ``target_root``.

    This deliberately restores into a caller-selected root instead of writing to
    the original absolute paths stored in the manifest. Operators can inspect
    the recovered tree and then move files into place during a controlled
    maintenance window.
    """
    archive = archive_path.expanduser()
    root = target_root.expanduser().resolve(strict=False)
    ensure_private_dir(root)

    restored: list[Path] = []
    with tarfile.open(archive, mode="r:gz") as tar:
        manifest = _read_manifest(tar)
        raw_items = manifest.get("items")
        if not isinstance(raw_items, list):
            msg = "backup manifest does not contain an items list"
            raise ValueError(msg)

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                msg = "backup manifest contains an invalid item"
                raise ValueError(msg)
            archive_name = raw_item.get("archive_path")
            expected_hash = raw_item.get("sha256")
            if not isinstance(archive_name, str) or not isinstance(expected_hash, str):
                msg = "backup manifest item is missing archive_path or sha256"
                raise ValueError(msg)
            member = _get_regular_member(tar, archive_name)
            destination = _safe_restore_path(root, archive_name)
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)
            _restore_member(tar, member, destination, expected_hash)
            restored.append(destination)

    return RestoreResult(target_root=root, files_restored=tuple(restored), manifest=manifest)


def _resolve_archive_output(output: Path | None) -> Path:
    filename = f"juris-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    if output is None:
        return default_backup_dir() / filename

    expanded = output.expanduser()
    if expanded.exists() and expanded.is_dir():
        return expanded / filename
    if expanded.name.endswith((".tar.gz", ".tgz")):
        return expanded
    if expanded.suffix:
        return expanded
    return expanded / filename


def _excluded_backup_roots(archive_path: Path) -> tuple[Path, ...]:
    roots = [default_backup_dir().resolve(strict=False)]
    if archive_path.parent.name.lower() in {"backup", "backups"}:
        roots.append(archive_path.parent.resolve(strict=False))
    return tuple(dict.fromkeys(roots))


def _collect_backup_files(
    juris_home_path: Path,
    *,
    out_root: Path,
    repertory_path: Path,
    include_out_root: bool,
    excluded_roots: Iterable[Path],
    warnings: list[str],
) -> list[_CollectedFile]:
    seen: set[Path] = set()
    collected: list[_CollectedFile] = []

    _collect_root(
        juris_home_path,
        archive_prefix="juris_home",
        group="juris_home",
        excluded_roots=excluded_roots,
        seen=seen,
        collected=collected,
        warnings=warnings,
    )
    if include_out_root:
        _collect_root(
            out_root,
            archive_prefix="out_root",
            group="out_root",
            excluded_roots=excluded_roots,
            seen=seen,
            collected=collected,
            warnings=warnings,
        )
    if repertory_path.exists():
        _collect_path(
            repertory_path,
            archive_path=f"repertory/{repertory_path.name}",
            group="repertory",
            excluded_roots=excluded_roots,
            seen=seen,
            collected=collected,
            warnings=warnings,
        )
    else:
        warnings.append(f"repertory db not found: {repertory_path}")

    return sorted(collected, key=lambda item: item.archive_path)


def _collect_root(
    root: Path,
    *,
    archive_prefix: str,
    group: str,
    excluded_roots: Iterable[Path],
    seen: set[Path],
    collected: list[_CollectedFile],
    warnings: list[str],
) -> None:
    if not root.exists():
        warnings.append(f"root not found: {root}")
        return
    if root.is_file():
        _collect_path(
            root,
            archive_path=f"{archive_prefix}/{root.name}",
            group=group,
            excluded_roots=excluded_roots,
            seen=seen,
            collected=collected,
            warnings=warnings,
        )
        return

    root_resolved = root.resolve()
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        try:
            relative = path.resolve().relative_to(root_resolved).as_posix()
        except ValueError:
            warnings.append(f"skipped file outside root: {path}")
            continue
        _collect_path(
            path,
            archive_path=f"{archive_prefix}/{relative}",
            group=group,
            excluded_roots=excluded_roots,
            seen=seen,
            collected=collected,
            warnings=warnings,
        )


def _collect_path(
    path: Path,
    *,
    archive_path: str,
    group: str,
    excluded_roots: Iterable[Path],
    seen: set[Path],
    collected: list[_CollectedFile],
    warnings: list[str],
) -> None:
    if path.is_symlink():
        warnings.append(f"skipped symlink: {path}")
        return
    if not path.is_file():
        return

    resolved = path.resolve()
    if _is_under_any(resolved, excluded_roots):
        return
    if resolved in seen:
        return
    seen.add(resolved)
    collected.append(_CollectedFile(source_path=resolved, archive_path=archive_path, group=group))


def _is_under_any(path: Path, roots: Iterable[Path]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _write_backup_archive(archive_path: Path, files: list[_CollectedFile], manifest: dict[str, object]) -> None:
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    with tarfile.open(archive_path, mode="w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest_bytes)
        info.mtime = int(datetime.now(UTC).timestamp())
        info.mode = 0o600
        tar.addfile(info, io.BytesIO(manifest_bytes))

        for item in files:
            tar.add(item.source_path, arcname=item.archive_path, recursive=False)


def _read_manifest(tar: tarfile.TarFile) -> dict[str, object]:
    try:
        member = tar.getmember(MANIFEST_NAME)
    except KeyError as exc:
        msg = "backup archive is missing manifest.json"
        raise ValueError(msg) from exc
    stream = tar.extractfile(member)
    if stream is None:
        msg = "backup manifest cannot be read"
        raise ValueError(msg)
    with stream:
        data: Any = json.load(stream)
    if not isinstance(data, dict):
        msg = "backup manifest is not a JSON object"
        raise ValueError(msg)
    return cast("dict[str, object]", data)


def _get_regular_member(tar: tarfile.TarFile, archive_name: str) -> tarfile.TarInfo:
    try:
        member = tar.getmember(archive_name)
    except KeyError as exc:
        msg = f"backup archive is missing {archive_name}"
        raise ValueError(msg) from exc
    if not member.isfile():
        msg = f"backup member is not a regular file: {archive_name}"
        raise ValueError(msg)
    return member


def _safe_restore_path(root: Path, archive_name: str) -> Path:
    candidate = (root / archive_name).resolve(strict=False)
    if not _is_relative_to(candidate, root):
        msg = f"unsafe backup path: {archive_name}"
        raise ValueError(msg)
    return candidate


def _restore_member(tar: tarfile.TarFile, member: tarfile.TarInfo, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stream = tar.extractfile(member)
    if stream is None:
        msg = f"backup member cannot be read: {member.name}"
        raise ValueError(msg)
    tmp = destination.with_name(f".{destination.name}.restore_tmp")
    digest = _copy_stream(stream, tmp)
    if digest != expected_hash:
        tmp.unlink(missing_ok=True)
        msg = f"sha256 mismatch restoring {member.name}"
        raise ValueError(msg)
    tmp.replace(destination)
    restrict_file(destination)


def _copy_stream(stream: IO[bytes], destination: Path) -> str:
    digest = hashlib.sha256()
    with stream, destination.open("wb") as out:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
