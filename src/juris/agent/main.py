"""Entrypoint standalone do agente Causia — para o PyInstaller empacotar sem o CLI/web.

Roda o agente loopback (`serve`). Pareamento e credenciais são browser-first
(o console dirige /pair-relay e /credentials no loopback). Na 1ª execução do
binário empacotado (macOS), instala o LaunchAgent e cede o controle a ele.
Auto-update roda no start. NÃO importa juris.cli.main nem juris.web (evita
puxar deps pesadas)."""
from __future__ import annotations

import os


def _render_launch_agent_plist(template: str, app_path: str, home: str) -> str:
    """Substitui os placeholders do template do LaunchAgent.

    Função pura (sem I/O) para poder testar a substituição isoladamente do
    resto de `_ensure_launch_agent`, que lida com filesystem/subprocess.

    Args:
        template: Conteúdo bruto do plist, com `__APP_PATH__`/`__HOME__`.
        app_path: Caminho absoluto do `.app` instalado (ex.:
            `~/Applications/Causia Agente.app`).
        home: Caminho absoluto do diretório home do usuário.

    Returns:
        O texto do plist com os dois placeholders substituídos.
    """
    return template.replace("__APP_PATH__", app_path).replace("__HOME__", home)


def _ensure_launch_agent() -> None:
    """Instala o LaunchAgent na 1ª execução do binário empacotado (best-effort).

    Só faz algo quando rodando congelado pelo PyInstaller (`sys.frozen`) em
    macOS; em qualquer outro caso (dev, onedir manual, Linux/Windows) é no-op.

    Kill-switch: a env var `JURIS_AGENT_NO_LAUNCHD` (qualquer valor não-vazio)
    pula a instalação inteira — usada por smokes/CI para não instalar um job
    launchd persistente na máquina de dev.

    Se o plist alvo (`~/Library/LaunchAgents/com.causia.agent.plist`) já
    existir, assume-se que é uma execução normal disparada pelo próprio
    launchd (RunAtLoad) e a função apenas retorna para seguir servindo.

    Caso contrário, lê o template embutido em
    `<App>.app/Contents/Resources/com.causia.agent.plist`, substitui os
    placeholders, grava o plist alvo, carrega via `launchctl load -w` e
    encerra o processo atual (`SystemExit(0)`) — o launchd assume a partir
    daí (RunAtLoad); continuar serviria numa porta duplicada.

    Qualquer exceção (I/O, subprocess, template ausente) é engolida: o
    processo volta a servir normalmente, como se não estivesse empacotado.
    """
    if os.environ.get("JURIS_AGENT_NO_LAUNCHD"):
        return

    import sys

    if not (getattr(sys, "frozen", False) and sys.platform == "darwin"):
        return

    import subprocess
    from pathlib import Path

    try:
        exe_path = Path(sys.executable).resolve()
        app_path = next((p for p in exe_path.parents if p.suffix == ".app"), None)
        if app_path is None:
            return  # não está dentro de um .app — onedir puro, nada a instalar

        target = Path.home() / "Library" / "LaunchAgents" / "com.causia.agent.plist"
        if target.exists():
            return  # já instalado — esta é a execução disparada pelo launchd

        template_path = app_path / "Contents" / "Resources" / "com.causia.agent.plist"
        rendered = _render_launch_agent_plist(
            template_path.read_text(encoding="utf-8"), str(app_path), str(Path.home())
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")

        subprocess.run(["launchctl", "load", "-w", str(target)], check=False)  # noqa: S603, S607
    except Exception:  # noqa: BLE001 - instalação do LaunchAgent é best-effort
        return

    raise SystemExit(0)  # launchd assume a partir daqui (RunAtLoad)


def main() -> None:
    """Start the local agent ASGI server.

    On a packaged macOS first run, installs the LaunchAgent and exits so
    launchd takes over (see `_ensure_launch_agent`). Auto-update runs before
    serving (best-effort; never blocks startup). All credentials are resolved
    locally — nothing sent to orchestrator on wire.
    """
    _ensure_launch_agent()

    # Auto-update before serving (best-effort; never blocks the start).
    try:
        from juris.agent.update import maybe_self_update

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
