"""Keepalive do WebSocket do relay agente↔nuvem (Task 10).

Servidor e cliente usavam os defaults do `websockets`/uvicorn (20s/20s), o que
derrubava o canal ~100x/dia atrás de Cloudflare Tunnel + rede residencial
("keepalive ping timeout"). Este teste fixa 25s/75s no lado servidor
(`juris web`); o lado cliente (`api/local_agent.py`, dialer do relay reverso)
não é exercitável via CliRunner e é coberto por leitura de código + CHANGELOG
do agente (ver relatório da Task 10).
"""

from __future__ import annotations

from typer.testing import CliRunner

from juris.cli.main import app

runner = CliRunner()


def test_juris_web_configura_keepalive_ws(monkeypatch) -> None:
    import uvicorn

    captured: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kw: captured.update(kw))

    result = runner.invoke(app, ["web", "--host", "127.0.0.1", "--port", "0"])

    assert result.exit_code == 0
    assert captured["ws_ping_interval"] == 25.0
    assert captured["ws_ping_timeout"] == 75.0
