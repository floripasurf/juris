"""AI-session status for the operator console (ADR-0016/0018).

Tells the operator which AI is active and whether prompts are de-identified before
leaving the machine — the answer the lawyer needs before clicking "draft".
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from juris.api.browser_bridge import validate_bridge_url


def ai_session_status(
    *,
    anthropic_key: bool,
    browser_bridge: bool,
    ollama_reachable: bool,
    browser_bridge_url: str | None = None,
    native_host_manifest: str | None = None,
    browser_bridge_reachable: bool | None = None,
    declared_provider: str | None = None,
) -> dict[str, object]:
    """Resolve the active AI mode + de-id posture from what's available.

    Precedence: the lawyer's browser session (ADR-0018) > cloud API (de-identified)
    > local model. De-id is on for any off-device AI; local keeps PII on the box.
    ``declared_provider`` ("claude"/"chatgpt") tailors the browser copy + training
    opt-out step to the vendor the lawyer declared (spec 2026-07-05).
    """
    display = {"claude": "Claude.ai", "chatgpt": "ChatGPT"}.get(declared_provider or "", "Claude.ai/ChatGPT")
    training_optout = {
        "claude": "Claude.ai: Settings → Privacy → desative 'Help improve Claude'.",
        "chatgpt": "ChatGPT: Settings → Data Controls → 'Improve the model for everyone' = off.",
    }.get(
        declared_provider or "",
        "Claude.ai: Privacy → desative 'Help improve Claude'. ChatGPT: Data Controls → 'Improve the model' = off.",
    )
    bridge_valid = False
    bridge_error: str | None = None
    if browser_bridge:
        try:
            validate_bridge_url(browser_bridge_url or "")
            bridge_valid = True
        except ValueError as exc:
            bridge_error = str(exc)

    if bridge_valid:
        mode = "browser_session"
    elif anthropic_key:
        mode = "cloud_deid"
    else:
        mode = "local"
    native_host_installed = bool(native_host_manifest and Path(native_host_manifest).exists())
    effective_bridge_reachable = bool(browser_bridge_reachable) if bridge_valid else False
    if browser_bridge and not bridge_valid:
        browser_status = "invalid_url"
        browser_message = bridge_error or "configure JURIS_BROWSER_BRIDGE_URL para ws://127.0.0.1:<porta>"
    elif bridge_valid and native_host_installed and effective_bridge_reachable:
        browser_status = "ready"
        browser_message = f"bridge ativo; mantenha {display} logado e aberto"
    elif bridge_valid and native_host_installed:
        browser_status = "agent_offline"
        browser_message = f"host instalado, mas bridge WS não respondeu; recarregue a extensão e abra {display}"
    elif bridge_valid:
        browser_status = "needs_native_host"
        browser_message = "configure o host nativo com `juris browser install-native-host`"
    else:
        browser_status = "disabled"
        browser_message = "defina JURIS_BROWSER_BRIDGE_URL após instalar a extensão"
    return {
        "mode": mode,
        "deidentify": mode != "local",
        "providers": {"cloud": anthropic_key, "browser": bridge_valid, "local": ollama_reachable},
        "browser": {
            "configured": browser_bridge,
            "valid_url": bridge_valid,
            "native_host_installed": native_host_installed,
            "bridge_reachable": effective_bridge_reachable,
            "status": browser_status,
            "message": browser_message,
            "declared_provider": declared_provider,
            "training_optout": training_optout,
        },
    }


def _bridge_reachable(url: str | None, *, timeout: float = 0.2) -> bool:
    if not url:
        return False
    try:
        bridge_url = validate_bridge_url(url)
    except ValueError:
        return False
    parsed = urlparse(bridge_url)
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
    from juris.llm.browser_session import normalize_browser_provider

    return ai_session_status(
        anthropic_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
        browser_bridge=bool(bridge_url),
        browser_bridge_url=bridge_url,
        native_host_manifest=manifest_path,
        browser_bridge_reachable=_bridge_reachable(bridge_url),
        ollama_reachable=bool(os.environ.get("OLLAMA_URL")),
        declared_provider=normalize_browser_provider(os.environ.get("JURIS_AI_BROWSER_PROVIDER")),
    )
