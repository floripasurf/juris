"""`juris agent` pairing + health CLI (ADR-0015)."""

from __future__ import annotations

from typer.testing import CliRunner

from juris.cli.main import app


def test_agent_pair_prints_both_env_vars() -> None:
    result = CliRunner().invoke(app, ["agent", "pair"])
    assert result.exit_code == 0
    assert "JURIS_AGENT_TOKEN=" in result.output
    assert "JURIS_LOCAL_AGENT_TOKEN=" in result.output


def test_agent_health_exits_nonzero_when_unreachable() -> None:
    result = CliRunner().invoke(app, ["agent", "health", "--url", "ws://127.0.0.1:59999"])
    assert result.exit_code == 1
    assert "inacessível" in result.output
