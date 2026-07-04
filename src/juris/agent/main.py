"""Entrypoint standalone do agente Causia — para o PyInstaller empacotar sem o CLI/web.

Roda o agente loopback (`serve`). Pareamento e credenciais são browser-first
(o console dirige /pair-relay e /credentials no loopback). Auto-update roda no
start. NÃO importa juris.cli.main nem juris.web (evita puxar deps pesadas)."""
from __future__ import annotations

import os


def main() -> None:
    """Start the local agent ASGI server.

    Auto-update runs before serving (best-effort; never blocks startup).
    All credentials are resolved locally — nothing sent to orchestrator on wire.
    """
    # Auto-update before serving (best-effort; never blocks the start).
    try:
        from juris.agent.update import maybe_self_update  # type: ignore[import-untyped]

        maybe_self_update()
    except Exception:  # noqa: BLE001, S110 - update is best-effort, never crashes the agent
        pass

    import uvicorn

    from juris.api.local_agent import app as agent_asgi
    from juris.api.local_agent import validate_local_agent_host

    host = validate_local_agent_host(os.environ.get("JURIS_AGENT_HOST", "127.0.0.1"))
    port = int(os.environ.get("JURIS_AGENT_PORT", "8765"))
    uvicorn.run(agent_asgi, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
