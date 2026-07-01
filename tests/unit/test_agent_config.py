"""Tests for split-trust agent config — URL normalisation (ADR-0015)."""

from __future__ import annotations

import pytest

from juris.api.agent_config import local_agent_base_url


def test_base_url_strips_a_ws_path_so_it_is_never_doubled(monkeypatch) -> None:
    # an operator who pastes the full /ws/sign URL still gets the base
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765/ws/sign")
    assert local_agent_base_url() == "ws://127.0.0.1:8765"


def test_base_url_keeps_a_clean_base(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://agent.example:8765")
    assert local_agent_base_url() == "ws://agent.example:8765"


def test_base_url_raises_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("JURIS_LOCAL_AGENT_URL", raising=False)
    with pytest.raises(RuntimeError, match="JURIS_LOCAL_AGENT_URL"):
        local_agent_base_url()


def test_base_url_rejects_a_url_without_scheme(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "127.0.0.1:8765")
    with pytest.raises(RuntimeError, match="inválida"):
        local_agent_base_url()


# --- per-tenant agent routing (multi-tenant keystone) ---


def test_tenant_binding_from_agents_file(tmp_path, monkeypatch) -> None:
    import json

    from juris.api.agent_config import tenant_agent_binding

    agents = tmp_path / "agents.json"
    agents.write_text(
        json.dumps(
            {
                "escritorio-a": {"url": "ws://a.local:8765/ws/sign", "token": "tok-a"},
                "escritorio-b": {"url": "ws://b.local:8765", "token": "tok-b"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    from juris.api.agent_config import _load_agent_bindings

    _load_agent_bindings.cache_clear()

    a = tenant_agent_binding("escritorio-a")
    assert a.base_url == "ws://a.local:8765"  # path normalised
    assert a.token == "tok-a"  # noqa: S105
    b = tenant_agent_binding("escritorio-b")
    assert b.base_url == "ws://b.local:8765"
    assert b.token == "tok-b"  # noqa: S105


def test_tenant_binding_falls_back_to_global_env(tmp_path, monkeypatch) -> None:
    from juris.api.agent_config import _load_agent_bindings, tenant_agent_binding

    monkeypatch.delenv("JURIS_AGENTS_FILE", raising=False)
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://global:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "global-tok")
    _load_agent_bindings.cache_clear()

    binding = tenant_agent_binding("public")
    assert binding.base_url == "ws://global:8765"
    assert binding.token == "global-tok"  # noqa: S105


def test_binding_fails_closed_when_agents_file_set_but_tenant_missing(tmp_path, monkeypatch) -> None:
    import json

    from juris.api.agent_config import _load_agent_bindings, tenant_agent_binding

    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"escritorio-a": {"url": "ws://a:8765", "token": "t"}}), encoding="utf-8")
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    _load_agent_bindings.cache_clear()

    with pytest.raises(RuntimeError, match="sem binding"):
        tenant_agent_binding("escritorio-desconhecido")  # not in the map → no silent global fallback


def test_binding_fails_closed_when_require_tenants(monkeypatch) -> None:
    from juris.api.agent_config import _load_agent_bindings, tenant_agent_binding

    monkeypatch.delenv("JURIS_AGENTS_FILE", raising=False)
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://global:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "g")
    _load_agent_bindings.cache_clear()

    with pytest.raises(RuntimeError, match="sem binding"):
        tenant_agent_binding("qualquer")


def test_binding_reloads_when_agents_file_changes(tmp_path, monkeypatch) -> None:
    import json
    import os

    from juris.api.agent_config import tenant_agent_binding

    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"a": {"url": "ws://one:8765", "token": "t"}}), encoding="utf-8")
    os.utime(agents, (1000, 1000))
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    assert tenant_agent_binding("a").base_url == "ws://one:8765"

    # rewrite with a NEW url + bump mtime — no explicit cache_clear
    agents.write_text(json.dumps({"a": {"url": "ws://two:8765", "token": "t"}}), encoding="utf-8")
    os.utime(agents, (2000, 2000))
    assert tenant_agent_binding("a").base_url == "ws://two:8765"  # rotation without restart
