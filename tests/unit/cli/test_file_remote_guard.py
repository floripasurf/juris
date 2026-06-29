"""`juris file` routes through the filing service — remote works via /ws/file (ADR-0015).

The old "refuse remote mode" guard is gone: filing now goes through
get_filing_service(), which is InProcess locally or Remote (forwarding to the
agent's /ws/file) when JURIS_AGENT_MODE=remote — no code change.
"""

from __future__ import annotations

from typer.testing import CliRunner

from juris.cli.main import app


def test_file_has_no_remote_guard_message(monkeypatch) -> None:
    # default (inprocess): the command must not print the removed guard message
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    result = CliRunner().invoke(
        app, ["file", "bad-cnj", "contestacao", "--cpf", "x", "--skip-preflight", "--dry-run"]
    )
    assert "não suporta modo remote" not in result.output


def test_file_remote_mode_routes_to_agent_not_a_guard(monkeypatch) -> None:
    # remote: no guard — the command proceeds toward the service (and fails later for
    # a bad draft, never at a "remote not supported" guard).
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:59999")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    result = CliRunner().invoke(
        app, ["file", "bad-cnj", "contestacao", "--cpf", "x", "--skip-preflight", "--dry-run"]
    )
    assert "não suporta modo remote" not in result.output
