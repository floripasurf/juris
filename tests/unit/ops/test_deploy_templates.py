"""Regression tests for launchd/runbook deploy contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_web_launchd_template_uses_tenant_agents_file() -> None:
    text = _read("docs/deploy/com.juris.web.plist")
    assert "<key>JURIS_REQUIRE_TENANTS</key>" in text
    assert "<key>JURIS_AGENT_MODE</key>" in text
    assert "<key>JURIS_AGENTS_FILE</key>" in text
    assert "<key>JURIS_LOCAL_AGENT_TOKEN</key>" not in text


def test_agent_launchd_template_uses_direct_entrypoint_and_private_logs() -> None:
    text = _read("docs/deploy/com.juris.agent.plist")
    assert "/usr/local/bin/uv" not in text
    assert "uv run" not in text
    assert ".venv/bin/juris" in text
    assert "/tmp/juris-agent" not in text
    assert "logs/agent.log" in text
    assert "logs/agent.err" in text


def test_pilot_doctor_wrapper_loads_service_environment() -> None:
    text = _read("scripts/doctor_juris_pilot.sh")
    assert "JURIS_REQUIRE_TENANTS" in text
    assert "JURIS_TENANTS_FILE" in text
    assert "JURIS_AUDIT_HMAC_KEY" in text
    assert "JURIS_AGENT_MODE=remote" in text
    assert "JURIS_AGENTS_FILE" in text
    assert "exec uv run juris doctor" in text
