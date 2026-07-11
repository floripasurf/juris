from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from juris.cli.main import app


def test_browser_install_native_host_prints_export() -> None:
    installation = SimpleNamespace(
        manifest_path=Path("/opt/juris/com.juris.host.json"),
        launcher_path=Path("/opt/juris/juris-native-host"),
        bridge_url="ws://127.0.0.1:8787",
    )
    with patch("juris.api.native_host.install_native_host", return_value=installation) as mocked:
        result = CliRunner().invoke(
            app,
            [
                "browser",
                "install-native-host",
                "--extension-id",
                "abcdefghijklmnopabcdefghijklmnop",
                "--port",
                "8787",
            ],
        )

    assert result.exit_code == 0
    mocked.assert_called_once_with(
        extension_id="abcdefghijklmnopabcdefghijklmnop",
        browser="chrome",
        ws_port=8787,
    )
    assert "JURIS_BROWSER_BRIDGE_URL=ws://127.0.0.1:8787" in result.output


def test_browser_install_native_host_reports_operational_error() -> None:
    with patch("juris.api.native_host.install_native_host", side_effect=RuntimeError("sem suporte")):
        result = CliRunner().invoke(
            app,
            [
                "browser",
                "install-native-host",
                "--extension-id",
                "abcdefghijklmnopabcdefghijklmnop",
            ],
        )

    assert result.exit_code == 1
    assert "sem suporte" in result.output


def test_browser_status_prints_readiness() -> None:
    status = {
        "mode": "browser_session",
        "deidentify": True,
        "browser": {
            "bridge_url": "ws://127.0.0.1:8787",
            "native_host_installed": True,
            "status": "ready",
            "message": "sessão browser configurada",
        },
    }
    with patch("juris.web.ai_status.resolve_ai_session_status", return_value=status):
        result = CliRunner().invoke(app, ["browser", "status"])

    assert result.exit_code == 0
    assert "browser_session" in result.output
    assert "Host nativo: instalado" in result.output
