"""Tests for operational backup/restore."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from juris.ops.backup import create_backup, restore_backup


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _tar_json(tar_path: Path, name: str) -> dict[str, object]:
    with tarfile.open(tar_path, mode="r:gz") as tar:
        member = tar.getmember(name)
        stream = tar.extractfile(member)
        assert stream is not None
        with stream:
            data = json.load(stream)
    assert isinstance(data, dict)
    return data


def test_create_backup_includes_legal_critical_artifacts(tmp_path: Path) -> None:
    home = tmp_path / "home"
    out = tmp_path / "out"
    corpus = tmp_path / "corpus" / "repertory.db"
    audit = _write(home / "audit.jsonl", '{"event":"case.created"}\n')
    _write(home / "audit.jsonl.anchor.json", '{"tail":"abc"}')
    _write(home / "tenants" / "escritorio-a" / "juris.db", "sqlite bytes")
    _write(home / "filings" / "cnj" / "receipt-1" / "receipt.json", '{"protocolo":"P1"}')
    _write(out / "case-1" / "draft.md", "minuta")
    _write(corpus, "corpus bytes")

    result = create_backup(
        output=tmp_path / "backups",
        juris_home_path=home,
        out_root=out,
        repertory_path=corpus,
    )

    assert result.archive_path.exists()
    assert result.checksum_path.exists()
    assert result.file_count == 6
    assert result.archive_sha256 in result.checksum_path.read_text(encoding="utf-8")

    with tarfile.open(result.archive_path, mode="r:gz") as tar:
        names = set(tar.getnames())
    assert "manifest.json" in names
    assert "juris_home/audit.jsonl" in names
    assert "juris_home/audit.jsonl.anchor.json" in names
    assert "juris_home/tenants/escritorio-a/juris.db" in names
    assert "juris_home/filings/cnj/receipt-1/receipt.json" in names
    assert "out_root/case-1/draft.md" in names
    assert "repertory/repertory.db" in names

    manifest = _tar_json(result.archive_path, "manifest.json")
    items = manifest["items"]
    assert isinstance(items, list)
    audit_item = next(
        item for item in items if isinstance(item, dict) and item["archive_path"] == "juris_home/audit.jsonl"
    )
    assert audit_item["sha256"] == hashlib.sha256(audit.read_bytes()).hexdigest()


def test_restore_backup_confines_and_verifies_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    out = tmp_path / "out"
    corpus = tmp_path / "corpus" / "repertory.db"
    _write(home / "audit.jsonl", "audit")
    _write(home / "filings" / "cnj" / "receipt-1" / "receipt.json", '{"ok":true}')
    _write(out / "case-1" / "draft.md", "draft")
    _write(corpus, "corpus")

    backup = create_backup(
        output=tmp_path / "backups",
        juris_home_path=home,
        out_root=out,
        repertory_path=corpus,
    )
    restored = restore_backup(backup.archive_path, target_root=tmp_path / "restore")

    assert (restored.target_root / "juris_home" / "audit.jsonl").read_text(encoding="utf-8") == "audit"
    assert (restored.target_root / "out_root" / "case-1" / "draft.md").read_text(encoding="utf-8") == "draft"
    assert (restored.target_root / "repertory" / "repertory.db").read_text(encoding="utf-8") == "corpus"
    assert len(restored.files_restored) == 4

    with pytest.raises(FileExistsError):
        restore_backup(backup.archive_path, target_root=tmp_path / "restore")


def test_restore_rejects_archive_path_traversal(tmp_path: Path) -> None:
    payload = b"owned"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "format": "juris-operational-backup",
        "version": 1,
        "items": [{"archive_path": "../evil.txt", "sha256": digest}],
    }
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, mode="w:gz") as tar:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_bytes)
        tar.addfile(manifest_info, io.BytesIO(manifest_bytes))
        payload_info = tarfile.TarInfo("../evil.txt")
        payload_info.size = len(payload)
        tar.addfile(payload_info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="unsafe backup path"):
        restore_backup(archive, target_root=tmp_path / "restore")

    assert not (tmp_path / "evil.txt").exists()
