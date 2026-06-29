"""Agent pairing — establish the shared secret + validate readiness (ADR-0015).

Pairing is how the orchestrator and the lawyer's local agent come to share an auth
token without a per-process random secret:

1. ``generate_pairing_token()`` mints a high-entropy token.
2. The operator sets it as ``JURIS_AGENT_TOKEN`` on the agent machine and
   ``JURIS_LOCAL_AGENT_TOKEN`` on the orchestrator (same value).
3. ``check_agent_health(url)`` confirms the agent is reachable and token-ready.

The CLI (``juris agent pair`` / ``juris agent health``) wraps these.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from juris.api.ws_schemas import HealthResponse

FetchJson = Callable[[str], "dict[str, object]"]


def generate_pairing_token() -> str:
    """A high-entropy URL-safe token to pair the orchestrator with the agent."""
    return secrets.token_urlsafe(32)


def _http_get_json(url: str) -> dict[str, object]:
    import httpx

    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    data: dict[str, object] = resp.json()
    return data


def check_agent_health(base_url: str, *, fetch: FetchJson | None = None) -> HealthResponse:
    """GET ``<base_url>/health`` and parse it; raise if the agent is unreachable.

    A ``ws://`` agent URL is probed over ``http://`` (same host/port).
    """
    http_base = base_url.replace("ws://", "http://").replace("wss://", "https://").rstrip("/")
    url = f"{http_base}/health"
    try:
        data = (fetch or _http_get_json)(url)
    except Exception as exc:  # noqa: BLE001 — any transport error ⇒ unreachable
        msg = f"agente inacessível em {url}: {exc}"
        raise RuntimeError(msg) from exc
    return HealthResponse.model_validate(data)
