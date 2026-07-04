# tests/unit/agent/test_launch_agent.py
from __future__ import annotations

import plistlib
from pathlib import Path


def _template() -> str:
    path = (
        Path(__file__).resolve().parents[3] / "packaging" / "agent" / "macos" / "com.causia.agent.plist"
    )
    return path.read_text(encoding="utf-8")


def test_both_placeholders_substituted() -> None:
    from juris.agent.main import _render_launch_agent_plist

    app_path = "/Users/advogado/Applications/Causia Agente.app"
    home = "/Users/advogado"
    rendered = _render_launch_agent_plist(_template(), app_path, home)

    assert f"{app_path}/Contents/MacOS/causia-agent" in rendered
    assert f"{home}/Library/Logs/causia-agent.log" in rendered
    assert f"{home}/Library/Logs/causia-agent.err" in rendered


def test_no_placeholder_left() -> None:
    from juris.agent.main import _render_launch_agent_plist

    rendered = _render_launch_agent_plist(_template(), "/Applications/Causia Agente.app", "/Users/advogado")

    assert "__APP_PATH__" not in rendered
    assert "__HOME__" not in rendered


def test_rendered_plist_is_valid_xml() -> None:
    from juris.agent.main import _render_launch_agent_plist

    rendered = _render_launch_agent_plist(_template(), "/Applications/Causia Agente.app", "/Users/advogado")

    parsed = plistlib.loads(rendered.encode())
    assert parsed["Label"] == "com.causia.agent"
    assert parsed["ProgramArguments"] == ["/Applications/Causia Agente.app/Contents/MacOS/causia-agent"]
    assert parsed["RunAtLoad"] is True
    assert parsed["KeepAlive"] is True
    assert parsed["StandardOutPath"] == "/Users/advogado/Library/Logs/causia-agent.log"
    assert parsed["StandardErrorPath"] == "/Users/advogado/Library/Logs/causia-agent.err"
