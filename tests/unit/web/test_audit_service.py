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
    assert view["audit_file"] == "audit.jsonl"
    assert "path" not in view
    assert str(tmp_path) not in str(view)
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


def test_resolve_audit_path_confines_to_root(tmp_path) -> None:
    from juris.web.audit_service import resolve_audit_path

    root = tmp_path / "juris-out"
    (root / "CASO-1").mkdir(parents=True)
    assert resolve_audit_path("CASO-1", root=root) == root / "CASO-1" / "audit.jsonl"


def test_resolve_audit_path_accepts_absolute_under_root(tmp_path) -> None:
    from juris.web.audit_service import resolve_audit_path

    root = tmp_path / "juris-out"
    case = root / "CASO-1"
    case.mkdir(parents=True)
    assert resolve_audit_path(str(case), root=root) == case / "audit.jsonl"


def test_resolve_audit_path_rejects_traversal(tmp_path) -> None:
    import pytest

    from juris.web.audit_service import resolve_audit_path

    root = tmp_path / "juris-out"
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="fora"):
        resolve_audit_path("../../etc", root=root)
