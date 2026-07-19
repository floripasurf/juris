"""Tests for the tenant-scoped operational support ledger."""

from __future__ import annotations

import json
import stat

from juris.web.operational_events import (
    append_operational_event,
    list_operational_events,
    operational_events_path,
    summarize_operational_events,
)


def test_operational_event_is_private_sanitized_and_summarized(tmp_path) -> None:
    append_operational_event(
        tmp_path,
        operation="demo.run",
        code="agent_mni_failed",
        message="Falha operacional no demo.",
        status_code=400,
        exc=RuntimeError("token=super-secret /Users/raphael/private"),
        numero_cnj="0001234-56.2026.8.13.0001",
    )

    path = operational_events_path(tmp_path)
    dumped = path.read_text(encoding="utf-8")
    events = list_operational_events(tmp_path)
    summary = summarize_operational_events(tmp_path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "super-secret" not in dumped
    assert "/Users/raphael/private" not in dumped
    assert events[0]["numero_cnj"] == "0001234-56.2026.8.13.0001"
    assert summary["total_events"] == 1
    assert summary["by_operation"] == {"demo.run": 1}
    assert summary["by_code"] == {"agent_mni_failed": 1}


def test_operational_event_reader_ignores_malformed_line(tmp_path) -> None:
    path = operational_events_path(tmp_path)
    path.write_text('{"code": "valid", "created_at": "2026-07-19T00:00:00+00:00"}\nnot-json\n', encoding="utf-8")

    assert len(list_operational_events(tmp_path)) == 1
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["code"] == "valid"
