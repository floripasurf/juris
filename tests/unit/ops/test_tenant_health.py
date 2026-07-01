"""Tests for per-tenant operational health."""

from __future__ import annotations

from juris.ops.tenant_health import tenant_operational_status
from juris.web.auth import Tenant


def test_status_reports_all_components(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)  # co-located
    status = tenant_operational_status(Tenant("public"))
    assert status["tenant_id"] == "public"
    assert set(status["components"]) == {"config", "storage", "corpus", "agent", "relay", "browser_bridge"}
    assert status["components"]["storage"]["ok"] is True  # DB + filing writable
    assert status["components"]["agent"]["ok"] is True  # co-located


def test_deep_browser_bridge_surfaces_invalid_token(monkeypatch, tmp_path) -> None:
    # A reachable bridge whose token is rejected must show the tenant DEGRADED, not ok.
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    monkeypatch.setenv("JURIS_BROWSER_BRIDGE_URL", "ws://127.0.0.1:8787")
    monkeypatch.setenv("JURIS_BROWSER_BRIDGE_TOKEN", "s3cret")

    import juris.api.browser_bridge as bb
    from juris.ops import tenant_health

    monkeypatch.setattr(bb, "probe_bridge", lambda url, token, **kw: (False, "token do bridge inválido"))
    tenant_health._probe_cache.clear()

    status = tenant_operational_status(Tenant("public"), deep=True)
    bridge = status["components"]["browser_bridge"]
    assert bridge["ok"] is False
    assert "token" in bridge["detail"].lower()
    assert status["status"] == "degraded"


def test_cached_probe_reuses_within_ttl() -> None:
    from juris.ops.tenant_health import _cached_probe, _probe_cache

    _probe_cache.clear()
    calls: list[int] = []

    def probe() -> tuple[bool, str]:
        calls.append(1)
        return (True, "ok")

    assert _cached_probe(("k",), probe) == (True, "ok")
    assert _cached_probe(("k",), probe) == (True, "ok")
    assert len(calls) == 1  # second call served from the short-TTL cache


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
