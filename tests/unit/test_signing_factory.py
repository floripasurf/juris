"""Tests for the signing-service factory — config picks InProcess vs Remote (ADR-0015)."""

from __future__ import annotations

import pytest

from juris.signing.factory import get_signing_service
from juris.signing.remote import RemoteSigningService
from juris.signing.service import InProcessSigningService


def test_inprocess_by_default(monkeypatch) -> None:
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    assert isinstance(get_signing_service(), InProcessSigningService)


def test_remote_when_mode_is_remote(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    assert isinstance(get_signing_service(), RemoteSigningService)


def test_remote_requires_agent_url(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.delenv("JURIS_LOCAL_AGENT_URL", raising=False)
    with pytest.raises(RuntimeError, match="JURIS_LOCAL_AGENT_URL"):
        get_signing_service()


def test_remote_fails_early_when_token_empty(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.delenv("JURIS_LOCAL_AGENT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="JURIS_LOCAL_AGENT_TOKEN"):
        get_signing_service()


def test_agent_token_comes_from_env_for_pairing(monkeypatch) -> None:
    from juris.api import local_agent

    monkeypatch.setenv("JURIS_AGENT_TOKEN", "shared-pairing-secret")
    local_agent._resolve_signing_token.cache_clear()
    try:
        assert local_agent.get_signing_token() == "shared-pairing-secret"
    finally:
        local_agent._resolve_signing_token.cache_clear()


def test_factory_routes_each_tenant_to_its_own_agent(tmp_path, monkeypatch) -> None:
    import json

    from juris.api.agent_config import _load_agent_bindings

    agents = tmp_path / "agents.json"
    agents.write_text(
        json.dumps({"escritorio-a": {"url": "ws://a.local:8765", "token": "tok-a"}}), encoding="utf-8"
    )
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://global:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "global-tok")
    _load_agent_bindings.cache_clear()

    svc_a = get_signing_service("escritorio-a")
    assert svc_a._transport._url == "ws://a.local:8765/ws/sign"  # routed to its own agent
    assert svc_a._transport._token == "tok-a"  # noqa: S105

    # with a tenant map configured, an unmapped tenant FAILS CLOSED (no silent global
    # fallback) so it can never reach the wrong firm's agent
    with pytest.raises(RuntimeError, match="sem binding"):
        get_signing_service("escritorio-desconhecido")
