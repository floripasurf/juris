"""Tests for the web audit viewer service (console #3)."""

from __future__ import annotations

import pytest

from juris.persistence.audit import AuditLog
from juris.web.audit_service import audit_view


def test_audit_view_returns_entries_and_intact(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.log("draft", "system", {"tese": "x"}, processo_cnj="A")
    log.log("sign", "user:123", {"hash": "y"}, processo_cnj="A")

    view = audit_view(path)

    assert view["total"] == 2
    assert view["intact"] is True
    assert view["corrupted"] == []
    assert view["entries"][0]["event_type"] == "draft"
    assert view["entries"][1]["actor"] == "user:123"
    assert view["entries"][0]["corrupted"] is False


def test_audit_view_flags_a_tampered_chain(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.log("draft", "system", {"a": 1})
    log.log("sign", "system", {"b": 2})
    # tamper: rewrite the first line's details so its content_hash no longer matches
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"a": 1', '"a": 999')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    view = audit_view(path)

    assert view["intact"] is False
    assert view["corrupted"]


def test_audit_view_raises_when_missing(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        audit_view(tmp_path / "nope.jsonl")
