"""Tests for juris.demo.audit_verify — `juris audit verify` backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from juris.demo.audit_verify import AuditVerificationReport, verify_audit_file
from juris.persistence.audit import AuditLog


class TestVerifyAuditFile:
    def test_intact_chain_reports_no_corruption(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = AuditLog(path)
        log.log("demo.started", "system", {"x": 1}, processo_cnj="cnj-1")
        log.log("demo.finished", "system", {"ok": True}, processo_cnj="cnj-1")

        report = verify_audit_file(path)

        assert isinstance(report, AuditVerificationReport)
        assert report.is_intact
        assert report.total_entries == 2
        assert report.corrupted_entry_ids == []

    def test_empty_file_reports_zero_entries_and_intact(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        path.write_text("")
        report = verify_audit_file(path)
        assert report.total_entries == 0
        assert report.is_intact

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            verify_audit_file(tmp_path / "nope.jsonl")

    def test_tampered_entry_marked_corrupted(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = AuditLog(path)
        log.log("a", "system", {"x": 1})
        log.log("b", "system", {"x": 2})

        # Corrupt the *content* of the second entry without recomputing its
        # hash. The hash check should reject it.
        lines = path.read_text().splitlines()
        record = json.loads(lines[1])
        record["details"]["x"] = 9999
        lines[1] = json.dumps(record, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n")

        report = verify_audit_file(path)
        assert not report.is_intact
        assert len(report.corrupted_entry_ids) == 1
        assert report.corrupted_entry_ids[0] == record["entry_id"]


class TestReportText:
    def test_intact_report_text_includes_ok(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        AuditLog(path).log("e", "system", {})
        text = verify_audit_file(path).to_text()
        assert "Chain integrity: OK" in text
        assert "Total entries: 1" in text

    def test_corrupted_report_text_lists_ids(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = AuditLog(path)
        log.log("a", "system", {"x": 1})

        # Tamper.
        line = json.loads(path.read_text().strip())
        line["details"]["x"] = 99
        path.write_text(json.dumps(line, ensure_ascii=False) + "\n")

        report = verify_audit_file(path)
        text = report.to_text()
        assert "FAILED" in text
        assert line["entry_id"] in text
