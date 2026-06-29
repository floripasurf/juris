"""Tests for the agent pairing flow (ADR-0015 — generate token + validate /health)."""

from __future__ import annotations

import pytest

from juris.api.pairing import check_agent_health, generate_pairing_token


def test_generate_pairing_token_is_strong_and_unique() -> None:
    a = generate_pairing_token()
    b = generate_pairing_token()
    assert a != b
    assert len(a) >= 32  # urlsafe, high-entropy
    assert " " not in a


def test_check_agent_health_parses_response() -> None:
    def _fetch(url: str) -> dict:
        assert url == "ws://127.0.0.1:8765/health" or url == "http://127.0.0.1:8765/health"
        return {
            "status": "ok",
            "token_connected": True,
            "cert_valid_until": "2030-05-01",
            "version": "0.1.0",
        }

    health = check_agent_health("http://127.0.0.1:8765", fetch=_fetch)
    assert health.token_connected is True
    assert str(health.cert_valid_until) == "2030-05-01"


def test_check_agent_health_normalises_ws_url() -> None:
    seen: list[str] = []

    def _fetch(url: str) -> dict:
        seen.append(url)
        return {"status": "ok", "token_connected": False}

    # a ws:// agent URL is probed over http:// for /health
    check_agent_health("ws://127.0.0.1:8765", fetch=_fetch)
    assert seen == ["http://127.0.0.1:8765/health"]


def test_check_agent_health_raises_on_unreachable() -> None:
    def _fetch(url: str) -> dict:
        raise ConnectionError("recusado")

    with pytest.raises(RuntimeError, match="inacessível"):
        check_agent_health("http://127.0.0.1:9999", fetch=_fetch)
