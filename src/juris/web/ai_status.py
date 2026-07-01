"""AI-session status for the operator console (ADR-0016/0018).

Tells the operator which AI is active and whether prompts are de-identified before
leaving the machine — the answer the lawyer needs before clicking "draft".
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse


def ai_session_status(
    *,
    anthropic_key: bool,
    browser_bridge: bool,
    ollama_reachable: bool,
    browser_bridge_url: str | None = None,
    native_host_manifest: str | None = None,
    browser_bridge_reachable: bool | None = None,
) -> dict[str, object]:
    """Resolve the active AI mode + de-id posture from what's available.

    Precedence: the lawyer's browser session (ADR-0018) > cloud API (de-identified)
    > local model. De-id is on for any off-device AI; local keeps PII on the box.
    """
    if browser_bridge:
        mode = "browser_session"
    elif anthropic_key:
        mode = "cloud_deid"
    else:
        mode = "local"
    native_host_installed = bool(native_host_manifest and Path(native_host_manifest).exists())
    if browser_bridge and native_host_installed and browser_bridge_reachable:
        browser_status = "ready"
        browser_message = "bridge ativo; mantenha Claude.ai/ChatGPT logado e aberto"
    elif browser_bridge and native_host_installed:
        browser_status = "agent_offline"
        browser_message = "host instalado, mas bridge WS não respondeu; recarregue a extensão e abra Claude.ai/ChatGPT"
    elif browser_bridge:
        browser_status = "needs_native_host"
        browser_message = "configure o host nativo com `juris browser install-native-host`"
    else:
        browser_status = "disabled"
        browser_message = "defina JURIS_BROWSER_BRIDGE_URL após instalar a extensão"
    return {
        "mode": mode,
        "deidentify": mode != "local",
        "providers": {"cloud": anthropic_key, "browser": browser_bridge, "local": ollama_reachable},
        "browser": {
            "configured": browser_bridge,
            "native_host_installed": native_host_installed,
            "bridge_reachable": browser_bridge_reachable,
            "status": browser_status,
            "message": browser_message,
        },
    }


def _bridge_reachable(url: str | None, *, timeout: float = 0.2) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or not parsed.port:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_ai_session_status() -> dict[str, object]:
    """Build the status from the live environment (the endpoint's entry point)."""
    bridge_url = os.environ.get("JURIS_BROWSER_BRIDGE_URL")
    try:
        from juris.api.native_host import default_manifest_path

        manifest_path = str(default_manifest_path())
    except RuntimeError:
        manifest_path = None
    return ai_session_status(
        anthropic_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
        browser_bridge=bool(bridge_url),
        browser_bridge_url=bridge_url,
        native_host_manifest=manifest_path,
        browser_bridge_reachable=_bridge_reachable(bridge_url),
        ollama_reachable=bool(os.environ.get("OLLAMA_URL")),
    )
