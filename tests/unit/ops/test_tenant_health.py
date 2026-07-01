"""Tests for per-tenant operational health."""

from __future__ import annotations

from juris.ops.tenant_health import tenant_operational_status
from juris.web.auth import Tenant


def test_status_reports_all_components(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)  # co-located
    status = tenant_operational_status(Tenant("public"))
    assert status["tenant_id"] == "public"
    assert set(status["components"]) == {"config", "storage", "corpus", "agent", "browser_bridge"}
    assert status["components"]["storage"]["ok"] is True  # DB + filing writable
    assert status["components"]["agent"]["ok"] is True  # co-located


def test_unrecognized_tenant_flags_config(monkeypatch, tmp_path) -> None:
    import json

    tenants = tmp_path / "tenants.json"
    from juris.web.auth import default_registry, hash_api_key

    tenants.write_text(json.dumps({"escritorio-a": hash_api_key("k")}), encoding="utf-8")
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    default_registry.cache_clear()
    try:
        status = tenant_operational_status(Tenant("intruso"))
        assert status["components"]["config"]["ok"] is False
    finally:
        default_registry.cache_clear()
