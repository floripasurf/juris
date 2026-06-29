"""`juris file` must refuse remote mode — filing is co-located (ADR-0015)."""

from __future__ import annotations

from typer.testing import CliRunner

from juris.cli.main import app


def test_file_rejects_remote_mode(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    result = CliRunner().invoke(
        app, ["file", "5082351-40.2017.8.13.0024", "contestacao", "--cpf", "07671039632"]
    )
    assert result.exit_code == 2
    assert "remote" in result.output.lower()


def test_file_allows_inprocess_mode_past_the_guard(monkeypatch) -> None:
    # inprocess (default) must NOT hit the remote guard — it fails later, not at the guard
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    result = CliRunner().invoke(
        app, ["file", "bad-cnj", "contestacao", "--cpf", "x", "--skip-preflight", "--dry-run"]
    )
    assert "não suporta modo remote" not in result.output
