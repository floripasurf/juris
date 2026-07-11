"""Tests for the AI-session status surfaced in the operator console (P3)."""

from __future__ import annotations

import json

from juris.web.ai_status import ai_session_status


def test_browser_session_mode_when_bridge_configured() -> None:
    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        browser_bridge_url="ws://127.0.0.1:8787",
        native_host_manifest="/var/empty/juris-nao-existe",
        ollama_reachable=True,
    )
    assert status["mode"] == "browser_session"
    assert status["deidentify"] is True  # de-id always on for off-device AI (ADR-0016)
    assert status["browser"]["status"] == "needs_native_host"
    assert status["browser"]["valid_url"] is True
    assert "native_host_manifest" not in status["browser"]
    assert "bridge_url" not in status["browser"]
    assert "/var/empty" not in json.dumps(status)


def test_invalid_browser_bridge_url_is_not_selected_or_echoed() -> None:
    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        browser_bridge_url="ws://127.0.0.1:8787?token=secret",
        native_host_manifest="/var/empty/juris-nao-existe",
        browser_bridge_reachable=True,
        ollama_reachable=True,
    )

    assert status["mode"] == "local"
    assert status["providers"]["browser"] is False
    assert status["browser"]["configured"] is True
    assert status["browser"]["valid_url"] is False
    assert status["browser"]["bridge_reachable"] is False
    assert status["browser"]["status"] == "invalid_url"
    assert "token=secret" not in json.dumps(status)


def test_cloud_deid_mode_when_only_anthropic() -> None:
    status = ai_session_status(anthropic_key=True, browser_bridge=False, ollama_reachable=False)
    assert status["mode"] == "cloud_deid"
    assert status["deidentify"] is True


def test_local_mode_when_neither_cloud_nor_browser() -> None:
    status = ai_session_status(anthropic_key=False, browser_bridge=False, ollama_reachable=True)
    assert status["mode"] == "local"
    assert status["deidentify"] is False  # PII stays on the machine — no de-id needed


def test_reports_provider_availability() -> None:
    status = ai_session_status(
        anthropic_key=True,
        browser_bridge=True,
        browser_bridge_url="ws://127.0.0.1:8787",
        ollama_reachable=False,
    )
    assert status["providers"] == {"cloud": True, "browser": True, "local": False}


def test_reports_browser_offline_when_manifest_exists_but_bridge_is_not_reachable(tmp_path) -> None:
    manifest = tmp_path / "com.juris.host.json"
    manifest.write_text("{}", encoding="utf-8")

    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        browser_bridge_url="ws://127.0.0.1:8787",
        native_host_manifest=str(manifest),
        browser_bridge_reachable=False,
        ollama_reachable=True,
    )

    assert status["browser"]["status"] == "agent_offline"
    assert status["browser"]["native_host_installed"] is True
    assert "native_host_manifest" not in status["browser"]
    assert "bridge_url" not in status["browser"]
    assert str(tmp_path) not in json.dumps(status)


def test_reports_browser_ready_when_bridge_is_reachable(tmp_path) -> None:
    manifest = tmp_path / "com.juris.host.json"
    manifest.write_text("{}", encoding="utf-8")

    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        browser_bridge_url="ws://127.0.0.1:8787",
        native_host_manifest=str(manifest),
        browser_bridge_reachable=True,
        ollama_reachable=True,
    )

    assert status["browser"]["status"] == "ready"
    assert status["browser"]["bridge_reachable"] is True
    assert "native_host_manifest" not in status["browser"]
    assert "bridge_url" not in status["browser"]
    assert str(tmp_path) not in json.dumps(status)


def test_status_names_declared_provider_chatgpt() -> None:
    from juris.web.ai_status import ai_session_status

    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        ollama_reachable=False,
        browser_bridge_url="ws://127.0.0.1:8777",
        native_host_manifest=None,
        browser_bridge_reachable=False,
        declared_provider="chatgpt",
    )
    browser = status["browser"]
    assert browser["declared_provider"] == "chatgpt"
    assert "ChatGPT" in browser["training_optout"]
    assert "Improve the model" in browser["training_optout"]


def test_status_without_declared_provider_keeps_generic_copy() -> None:
    from juris.web.ai_status import ai_session_status

    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        ollama_reachable=False,
        browser_bridge_url="ws://127.0.0.1:8777",
        native_host_manifest=None,
        browser_bridge_reachable=False,
    )
    browser = status["browser"]
    assert browser["declared_provider"] is None
    assert "Claude.ai" in browser["training_optout"] and "ChatGPT" in browser["training_optout"]
