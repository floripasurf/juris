"""Regression tests for --cloud flag in CLI review command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from juris.cli.main import app

runner = CliRunner()


@pytest.fixture()
def _mock_settings_with_key():
    """Mock get_settings returning a Settings with anthropic_api_key set."""
    mock_settings = MagicMock()
    mock_settings.anthropic_api_key = SecretStr("sk-test-key-123")
    with patch("juris.config.get_settings", return_value=mock_settings):
        yield mock_settings


@pytest.fixture()
def _mock_settings_no_key():
    """Mock get_settings returning a Settings with no anthropic_api_key."""
    mock_settings = MagicMock()
    mock_settings.anthropic_api_key = None
    with patch("juris.config.get_settings", return_value=mock_settings):
        yield mock_settings


class TestCloudFlag:
    """Tests for the --cloud LLM selection in the review command."""

    @pytest.mark.usefixtures("_mock_settings_with_key")
    def test_cloud_reads_api_key_from_settings(self, tmp_path: pytest.TempPathFactory) -> None:
        """--cloud should read the API key from Settings and pass it to ClaudeLLM."""
        petition = tmp_path / "peticao.md"
        petition.write_text("Teste de peticao.")

        with patch("juris.llm.claude.ClaudeLLM") as mock_claude:
            mock_claude.return_value = MagicMock()
            runner.invoke(app, ["review", str(petition), "--cloud"])

        mock_claude.assert_called_once_with(api_key="sk-test-key-123")

    @pytest.mark.usefixtures("_mock_settings_no_key")
    def test_cloud_missing_key_exits_with_error(self, tmp_path: pytest.TempPathFactory) -> None:
        """--cloud with no ANTHROPIC_API_KEY should exit with code 1."""
        petition = tmp_path / "peticao.md"
        petition.write_text("Teste de peticao.")

        result = runner.invoke(app, ["review", str(petition), "--cloud"])

        assert result.exit_code == 1
        assert "ANTHROPIC_API_KEY not configured" in result.output
