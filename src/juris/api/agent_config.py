"""Split-trust agent configuration (ADR-0015).

Reads the env that decides whether token operations run in-process (Phase 1,
co-located CLI/pilot) or are forwarded to the lawyer's local agent (Phase 2,
multi-tenant):

* ``JURIS_AGENT_MODE``   — ``inprocess`` (default) | ``remote``
* ``JURIS_LOCAL_AGENT_URL``   — ``ws://host:port`` of the agent (remote mode)
* ``JURIS_LOCAL_AGENT_TOKEN`` — shared secret authenticating the orchestrator
"""

from __future__ import annotations

import os


def agent_mode() -> str:
    """``"remote"`` or ``"inprocess"`` (default)."""
    return os.environ.get("JURIS_AGENT_MODE", "inprocess").strip().lower()


def is_remote() -> bool:
    return agent_mode() == "remote"


def local_agent_base_url() -> str:
    """The agent **base** URL (``scheme://host:port``), normalised.

    The factories append ``/ws/sign`` etc., so any path the operator includes is
    stripped — ``ws://host:8765/ws/sign`` and ``ws://host:8765`` both yield the base,
    never a doubled ``/ws/sign/ws/sign``. Raises in remote mode when unset/invalid.
    """
    from urllib.parse import urlparse, urlunparse

    url = os.environ.get("JURIS_LOCAL_AGENT_URL")
    if not url:
        msg = "JURIS_LOCAL_AGENT_URL é obrigatório no modo remote (ADR-0015)."
        raise RuntimeError(msg)
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        msg = f"JURIS_LOCAL_AGENT_URL inválida (use ws://host:porta): {url!r}"
        raise RuntimeError(msg)
    # keep only scheme://host:port — drop any /ws/... path the operator included
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def local_agent_token() -> str:
    """The shared secret authenticating the orchestrator to the agent (remote mode).

    Must match the agent's ``JURIS_AGENT_TOKEN`` (pairing). Raises when unset so a
    misconfigured remote deployment fails early instead of being rejected per call.
    """
    token = os.environ.get("JURIS_LOCAL_AGENT_TOKEN", "")
    if not token:
        msg = "JURIS_LOCAL_AGENT_TOKEN é obrigatório no modo remote (pareie com o agente)."
        raise RuntimeError(msg)
    return token
