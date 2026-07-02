"""Tests for the audit log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from juris.persistence.audit import AuditLog, _compute_hash, create_entry


class TestCreateEntry:
    def test_creates_with_all_fields(self) -> None:
        entry = create_entry(
            event_type="classify",
            actor="system",
            details={"codigo": 132, "categoria": "sentenca"},
            processo_cnj="1234567-89.2026.8.13.0001",
        )
        assert entry.entry_id
        assert entry.timestamp
        assert entry.event_type == "classify"
        assert entry.actor == "system"
        assert entry.processo_cnj == "1234567-89.2026.8.13.0001"
        assert entry.content_hash

    def test_hash_is_deterministic(self) -> None:
        timestamp = datetime(2026, 1, 2, tzinfo=UTC)
        details = {"a": 1, "b": "two"}
        h1 = _compute_hash(timestamp, "test", "system", "123", details)
        h2 = _compute_hash(timestamp, "test", "system", "123", details)
        assert h1 == h2

    def test_hash_changes_with_content(self) -> None:
        timestamp = datetime(2026, 1, 2, tzinfo=UTC)
        h1 = _compute_hash(timestamp, "test", "system", "123", {"a": 1})
        h2 = _compute_hash(timestamp, "test", "system", "123", {"a": 2})
        assert h1 != h2

    def test_to_dict(self) -> None:
        entry = create_entry("test", "system", {"key": "val"})
        d = entry.to_dict()
        assert isinstance(d["timestamp"], str)
        assert d["event_type"] == "test"


class TestAuditLog:
    def test_append_and_read(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        entry = create_entry("classify", "system", {"codigo": 132})
        log.append(entry)

        entries = log.read_all()
        assert len(entries) == 1
        assert entries[0].entry_id == entry.entry_id

    def test_log_shortcut(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        entry = log.log("sync", "system", {"processos": 5}, processo_cnj="123")
        assert entry.processo_cnj == "123"
        assert log.count == 1

    def test_multiple_entries(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})
        log.log("c", "system", {"x": 3})
        assert log.count == 3
        entries = log.read_all()
        assert [e.event_type for e in entries] == ["a", "b", "c"]

    def test_verify_integrity_passes(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        log.log("test", "system", {"data": "ok"})
        log.log("test2", "system", {"data": "also ok"})
        corrupted = log.verify_integrity()
        assert corrupted == []

    def test_verify_integrity_detects_tampering(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("test", "system", {"data": "original"})

        # Tamper with the file
        lines = log_path.read_text().strip().split("\n")
        entry_data = json.loads(lines[0])
        entry_data["details"]["data"] = "tampered"
        log_path.write_text(json.dumps(entry_data) + "\n")

        corrupted = log.verify_integrity()
        assert len(corrupted) == 1

    def test_verify_integrity_detects_timestamp_tampering(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("test", "system", {"data": "original"})

        entry_data = json.loads(log_path.read_text().strip())
        entry_data["timestamp"] = "2026-01-01T00:00:00+00:00"
        log_path.write_text(json.dumps(entry_data) + "\n")

        corrupted = log.verify_integrity()
        assert len(corrupted) == 1

    def test_verify_integrity_detects_actor_tampering(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("test", "system", {"data": "original"})

        entry_data = json.loads(log_path.read_text().strip())
        entry_data["actor"] = "user:tampered"
        log_path.write_text(json.dumps(entry_data) + "\n")

        corrupted = log.verify_integrity()
        assert len(corrupted) == 1

    def test_verify_integrity_detects_event_type_tampering(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("test", "system", {"data": "original"})

        entry_data = json.loads(log_path.read_text().strip())
        entry_data["event_type"] = "tampered"
        log_path.write_text(json.dumps(entry_data) + "\n")

        corrupted = log.verify_integrity()
        assert len(corrupted) == 1

    def test_empty_log(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        assert log.count == 0
        assert log.read_all() == []
        assert log.verify_integrity() == []

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "deep" / "nested" / "audit.jsonl")
        log.log("test", "system", {"ok": True})
        assert log.count == 1

    def test_chain_links_entries(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        e1 = log.log("a", "system", {"x": 1})
        e2 = log.log("b", "system", {"x": 2})
        e3 = log.log("c", "system", {"x": 3})
        assert e2.prev_hash == e1.content_hash
        assert e3.prev_hash == e2.content_hash

    def test_chain_first_entry_has_none_prev_hash(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        entry = log.log("first", "system", {"x": 1})
        assert entry.prev_hash is None

    def test_chain_detects_deleted_entry(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})
        log.log("c", "system", {"x": 3})

        # Remove middle entry
        lines = log_path.read_text().strip().split("\n")
        log_path.write_text(lines[0] + "\n" + lines[2] + "\n")

        corrupted = log.verify_integrity()
        assert len(corrupted) == 1  # third entry's prev_hash won't match first

    def test_chain_detects_reordered_entries(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})
        log.log("c", "system", {"x": 3})

        # Swap entries 2 and 3
        lines = log_path.read_text().strip().split("\n")
        log_path.write_text(lines[0] + "\n" + lines[2] + "\n" + lines[1] + "\n")

        corrupted = log.verify_integrity()
        assert len(corrupted) >= 1  # at least one chain break detected

    def test_append_rejects_unchained_entry_after_existing(self, tmp_path: Path) -> None:
        """append() rejects entries whose prev_hash doesn't match the log tail."""
        log = AuditLog(tmp_path / "audit.jsonl")
        log.log("a", "system", {"x": 1})

        # Create an entry with no prev_hash (as if bypassing log())
        rogue = create_entry("rogue", "attacker", {"x": "bypass"})
        assert rogue.prev_hash is None
        with pytest.raises(ValueError, match="Chain mismatch"):
            log.append(rogue)

    def test_append_rejects_wrong_prev_hash(self, tmp_path: Path) -> None:
        """append() rejects entries whose prev_hash is a valid hash but not the tail."""
        log = AuditLog(tmp_path / "audit.jsonl")
        e1 = log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})

        # Try to append with prev_hash pointing to e1 instead of e2
        rogue = create_entry("rogue", "attacker", {"x": "wrong"}, prev_hash=e1.content_hash)
        with pytest.raises(ValueError, match="Chain mismatch"):
            log.append(rogue)

    def test_verify_flags_unchained_entry_after_chain_starts(self, tmp_path: Path) -> None:
        """An unchained entry injected after chained entries is flagged."""
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})

        # Manually append a forged unchained entry (bypass append() by writing directly)
        forged = create_entry("forged", "attacker", {"x": "sneaky"})
        line = json.dumps(forged.to_dict(), ensure_ascii=False, default=str)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        corrupted = log.verify_integrity()
        assert forged.entry_id in corrupted

    def test_verify_flags_forged_entry_inserted_in_chain(self, tmp_path: Path) -> None:
        """A forged entry inserted mid-chain breaks the chain link."""
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path)
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})
        log.log("c", "system", {"x": 3})

        # Insert a forged entry between b and c
        lines = log_path.read_text().strip().split("\n")
        forged = create_entry("forged", "attacker", {"x": "insert"})
        forged_line = json.dumps(forged.to_dict(), ensure_ascii=False, default=str)
        log_path.write_text(
            lines[0] + "\n" + lines[1] + "\n" + forged_line + "\n" + lines[2] + "\n"
        )

        corrupted = log.verify_integrity()
        # The forged entry has prev_hash=None after chain started → flagged
        # Entry c's prev_hash points to b, but its predecessor is now the forged entry → flagged
        assert len(corrupted) >= 2

    def test_hmac_anchor_detects_tail_truncation(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path, hmac_key="anchor-secret")
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})
        log.log("c", "system", {"x": 3})

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        log_path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

        corrupted = log.verify_integrity()
        assert "__audit_anchor__" in corrupted

    def test_hmac_anchor_detects_head_truncation(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path, hmac_key="anchor-secret")
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})
        log.log("c", "system", {"x": 3})

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        log_path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")

        corrupted = log.verify_integrity()
        assert "__audit_anchor__" in corrupted

    def test_hmac_anchor_detects_anchor_tampering(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(log_path, hmac_key="anchor-secret")
        log.log("a", "system", {"x": 1})

        anchor_path = log_path.with_suffix(log_path.suffix + ".anchor.json")
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor["count"] = 99
        anchor_path.write_text(json.dumps(anchor), encoding="utf-8")

        corrupted = log.verify_integrity()
        assert "__audit_anchor__" in corrupted

    def test_legacy_entries_without_prev_hash_pass_integrity(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit.jsonl"
        # Write a legacy entry without prev_hash
        legacy = {
            "entry_id": "legacy-001",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "event_type": "test",
            "actor": "system",
            "processo_cnj": None,
            "details": {"data": "old"},
            "content_hash": _compute_hash(
                datetime(2026, 1, 1, tzinfo=UTC), "test", "system", None, {"data": "old"}
            ),
        }
        log_path.write_text(json.dumps(legacy) + "\n")

        log = AuditLog(log_path)
        entries = log.read_all()
        assert len(entries) == 1
        assert entries[0].prev_hash is None
        assert log.verify_integrity() == []
