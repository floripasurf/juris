"""Split-trust agent configuration + per-tenant routing (ADR-0015).

Decides whether token operations run in-process (Phase 1, co-located CLI/pilot) or
are forwarded to the lawyer's local agent (Phase 2, multi-tenant), and — crucially
for multi-tenant — **which** agent each tenant routes to:

* ``JURIS_AGENT_MODE``        — ``inprocess`` (default) | ``remote``
* ``JURIS_LOCAL_AGENT_URL``   — ``ws://host:port`` of the agent (single-tenant / fallback)
* ``JURIS_LOCAL_AGENT_TOKEN`` — shared secret authenticating the orchestrator
* ``JURIS_AGENTS_FILE``       — JSON ``{tenant_id: {"url", "token"}}`` mapping each
  firm to its own agent (multi-tenant routing); falls back to the env above.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse, urlunparse


def agent_mode() -> str:
    """``"remote"`` or ``"inprocess"`` (default)."""
    return os.environ.get("JURIS_AGENT_MODE", "inprocess").strip().lower()


def is_remote() -> bool:
    return agent_mode() == "remote"


def _normalize_base_url(url: str) -> str:
    """Reduce a URL to ``scheme://host:port``, dropping any ``/ws/...`` path.

    Both ``ws://host:8765/ws/sign`` and ``ws://host:8765`` yield the base, so the
    factories never produce a doubled ``/ws/sign/ws/sign``.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        msg = f"URL do agente inválida (use ws://host:porta): {url!r}"
        raise RuntimeError(msg)
    if parsed.username or parsed.password:
        msg = "URL do agente inválida: não inclua usuário/senha; use o token pareado separado."
        raise RuntimeError(msg)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def local_agent_base_url() -> str:
    """The single-tenant/fallback agent base URL from ``$JURIS_LOCAL_AGENT_URL``."""
    url = os.environ.get("JURIS_LOCAL_AGENT_URL")
    if not url:
        msg = "JURIS_LOCAL_AGENT_URL é obrigatório no modo remote (ADR-0015)."
        raise RuntimeError(msg)
    return _normalize_base_url(url)


def local_agent_token() -> str:
    """The single-tenant/fallback shared secret from ``$JURIS_LOCAL_AGENT_TOKEN``.

    Must match the agent's ``JURIS_AGENT_TOKEN`` (pairing). Raises when unset so a
    misconfigured remote deployment fails early instead of being rejected per call.
    """
    token = os.environ.get("JURIS_LOCAL_AGENT_TOKEN", "")
    if not token:
        msg = "JURIS_LOCAL_AGENT_TOKEN é obrigatório no modo remote (pareie com o agente)."
        raise RuntimeError(msg)
    return token


@dataclass(frozen=True, slots=True)
class AgentBinding:
    """Where a tenant's token operations are forwarded — its agent URL + token."""

    base_url: str
    token: str


@lru_cache(maxsize=4)
def _read_agent_bindings(path: str, _mtime: float) -> dict[str, dict[str, str]]:
    """Parse the agent map; keyed by (path, mtime) so a rewrite auto-invalidates."""
    with open(path, encoding="utf-8") as fh:
        data: dict[str, dict[str, str]] = json.load(fh)
    return data


def _load_agent_bindings() -> dict[str, dict[str, str]]:
    """Load the per-tenant agent map from ``$JURIS_AGENTS_FILE`` (empty if unset).

    Cached by file mtime, so rotating a token / onboarding a firm takes effect on the
    next request without an orchestrator restart (revocation isn't stuck behind a boot).
    """
    path = os.environ.get("JURIS_AGENTS_FILE")
    if not path or not os.path.exists(path):
        return {}
    return _read_agent_bindings(path, os.path.getmtime(path))


# Keep the historical `_load_agent_bindings.cache_clear()` API (tests/fixtures use it).
_load_agent_bindings.cache_clear = _read_agent_bindings.cache_clear  # type: ignore[attr-defined]


def _require_tenants() -> bool:
    """Whether a tenant must have its own agent binding (no silent global fallback)."""
    return os.environ.get("JURIS_REQUIRE_TENANTS", "").strip().lower() in {"1", "true", "yes"}


def tenant_agent_binding(tenant_id: str = "public") -> AgentBinding:
    """Resolve the agent a tenant routes to — its own (``$JURIS_AGENTS_FILE``) or the
    single-tenant fallback (``$JURIS_LOCAL_AGENT_URL`` / ``_TOKEN``).

    So each firm reaches *its* local agent (multi-tenant), and a co-located pilot
    keeps working off the env. **Fail-closed**: once a tenant map is configured (or
    ``JURIS_REQUIRE_TENANTS=1``), a tenant without its own binding raises instead of
    silently using the global agent/token — a misconfigured tenant must never reach
    another firm's agent. Raises when nothing resolves in remote mode.
    """
    from juris.web.auth import validate_tenant_id

    tenant_id = validate_tenant_id(tenant_id)
    bindings = _load_agent_bindings()
    entry = bindings.get(tenant_id)
    if entry is not None:
        if not entry.get("url") or not entry.get("token"):
            msg = f"binding do agente incompleto para o tenant {tenant_id!r} (precisa url + token)."
            raise RuntimeError(msg)
        return AgentBinding(_normalize_base_url(entry["url"]), entry["token"])

    if bindings or _require_tenants():
        msg = (
            f"tenant {tenant_id!r} sem binding de agente próprio "
            "(fail-closed: defina-o em JURIS_AGENTS_FILE)."
        )
        raise RuntimeError(msg)
    return AgentBinding(local_agent_base_url(), local_agent_token())
