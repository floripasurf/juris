"""Tests for the AI-session status surfaced in the operator console (P3)."""

from __future__ import annotations

from juris.web.ai_status import ai_session_status


def test_browser_session_mode_when_bridge_configured() -> None:
    status = ai_session_status(anthropic_key=False, browser_bridge=True, ollama_reachable=True)
    assert status["mode"] == "browser_session"
    assert status["deidentify"] is True  # de-id always on for off-device AI (ADR-0016)


def test_cloud_deid_mode_when_only_anthropic() -> None:
    status = ai_session_status(anthropic_key=True, browser_bridge=False, ollama_reachable=False)
    assert status["mode"] == "cloud_deid"
    assert status["deidentify"] is True


def test_local_mode_when_neither_cloud_nor_browser() -> None:
    status = ai_session_status(anthropic_key=False, browser_bridge=False, ollama_reachable=True)
    assert status["mode"] == "local"
    assert status["deidentify"] is False  # PII stays on the machine — no de-id needed


def test_reports_provider_availability() -> None:
    status = ai_session_status(anthropic_key=True, browser_bridge=True, ollama_reachable=False)
    assert status["providers"] == {"cloud": True, "browser": True, "local": False}
