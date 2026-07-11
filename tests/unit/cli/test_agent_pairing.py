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


def test_agent_serve_rejects_non_loopback() -> None:
    result = CliRunner().invoke(app, ["agent", "serve", "--host", "0.0.0.0"])  # noqa: S104
    assert result.exit_code == 2
    assert "127.0.0.1" in result.output


def test_agent_serve_binds_loopback(monkeypatch) -> None:
    import uvicorn

    from juris.api import local_agent

    monkeypatch.setenv("JURIS_AGENT_TOKEN", "paired-token")
    local_agent._resolve_signing_token.cache_clear()
    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kw: captured.update(kw))
    result = CliRunner().invoke(app, ["agent", "serve", "--port", "9999"])
    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9999
    assert captured["access_log"] is False  # request lines are unnecessary on the token holder


def test_agent_serve_fails_closed_without_token(monkeypatch) -> None:
    monkeypatch.delenv("JURIS_AGENT_TOKEN", raising=False)
    result = CliRunner().invoke(app, ["agent", "serve"])
    assert result.exit_code == 2  # refuses to start with an unknown random token
    assert "JURIS_AGENT_TOKEN" in result.output


def test_agent_serve_masks_the_token(monkeypatch) -> None:
    import uvicorn

    from juris.api import local_agent

    monkeypatch.setenv("JURIS_AGENT_TOKEN", "super-secret-pairing-token-value")
    local_agent._resolve_signing_token.cache_clear()
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kw: None)
    try:
        result = CliRunner().invoke(app, ["agent", "serve"])
    finally:
        local_agent._resolve_signing_token.cache_clear()
    assert result.exit_code == 0
    assert "super-secret-pairing-token-value" not in result.output  # masked, not echoed


def test_agent_connect_relay_rejects_invalid_tenant(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_AGENT_TOKEN", "paired-token")

    result = CliRunner().invoke(
        app,
        ["agent", "connect-relay", "wss://juris.example/ws/agent-relay", "--tenant", "../escape"],
    )

    assert result.exit_code == 2
    assert "tenant_id inválido" in result.output
