"""Per-tenant operational health — config, storage, corpus, agent, browser bridge.

Answers "is this firm actually able to work right now?" for one tenant, without
touching another tenant's data. Used by ``juris doctor --tenant`` and the
authenticated ``/api/health`` route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from juris.web.auth import Tenant


def _component(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def tenant_operational_status(tenant: Tenant, *, deep: bool = False) -> dict[str, Any]:
    """Return ``{tenant_id, status, components}`` for one tenant (never reads another's).

    ``deep=True`` also probes the remote agent over the network (best-effort).
    """
    components: dict[str, dict[str, Any]] = {}

    components["config"] = _check_config(tenant)
    components["storage"] = _check_storage(tenant)
    components["corpus"] = _check_corpus()
    components["agent"] = _check_agent(tenant, deep=deep)
    components["browser_bridge"] = _check_browser_bridge()

    healthy = all(c["ok"] for c in components.values())
    return {
        "tenant_id": tenant.tenant_id,
        "status": "ok" if healthy else "degraded",
        "components": components,
    }


def _check_config(tenant: Tenant) -> dict[str, Any]:
    from juris.web.auth import default_registry

    reg = default_registry()
    if reg.is_open:
        return _component(True, "registry aberto (piloto single-tenant)")
    known = tenant.tenant_id in reg.tenant_ids
    return _component(known, "reconhecido no registry" if known else "tenant não está no JURIS_TENANTS_FILE")


def _check_storage(tenant: Tenant) -> dict[str, Any]:
    from juris.core.paths import juris_home
    from juris.persistence.local_db import LocalDB
    from juris.web.auth import tenant_db_path, tenant_scoped_dir

    try:
        LocalDB(tenant_db_path(tenant)).ping()
    except Exception as exc:  # noqa: BLE001 — any failure ⇒ storage down
        return _component(False, f"banco inacessível: {exc}")

    # filing root writable (a probe file, removed immediately)
    filing_root = tenant_scoped_dir(tenant, juris_home()) / "filings"
    try:
        filing_root.mkdir(parents=True, exist_ok=True)
        probe = filing_root / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return _component(False, f"diretório de filing não gravável: {exc}")
    return _component(True, "banco e diretório de filing OK (isolados por tenant)")


def _check_corpus() -> dict[str, Any]:
    from juris.repertory.readiness import read_status

    status = read_status()
    return _component(status.is_ready, status.not_ready_reason or f"{status.chunk_count} chunks prontos")


def _check_agent(tenant: Tenant, *, deep: bool) -> dict[str, Any]:
    from juris.api.agent_config import is_remote

    if not is_remote():
        return _component(True, "modo co-localizado (token local)")

    from juris.api.agent_config import tenant_agent_binding

    try:
        binding = tenant_agent_binding(tenant.tenant_id)
    except RuntimeError as exc:
        return _component(False, f"sem binding de agente: {exc}")

    if not deep:
        return _component(True, f"binding configurado → {binding.base_url}")

    from juris.api.pairing import check_agent_health

    try:
        health = check_agent_health(binding.base_url)
    except RuntimeError as exc:
        return _component(False, f"agente inacessível: {exc}")
    return _component(
        health.token_connected,
        f"agente v{health.version}; token {'conectado' if health.token_connected else 'AUSENTE'}",
    )


def _check_browser_bridge() -> dict[str, Any]:
    import os

    from juris.api.browser_bridge import validate_bridge_url

    url = os.environ.get("JURIS_BROWSER_BRIDGE_URL")
    if not url:
        return _component(True, "bridge de browser não configurado (usa API de nuvem de-identificada)")
    try:
        validate_bridge_url(url)
    except (ValueError, RuntimeError) as exc:
        return _component(False, f"URL do bridge inválida: {exc}")
    return _component(True, f"bridge configurado: {url}")
