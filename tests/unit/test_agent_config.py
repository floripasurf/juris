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
