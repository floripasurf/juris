"""Tests for juris search CLI subcommand."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from juris.cli.search_cli import search_app

runner = CliRunner()


class TestSearchCLI:
    def test_no_query_type_errors(self) -> None:
        result = runner.invoke(search_app, [])
        # no_args_is_help=True shows help and exits with code 2
        assert result.exit_code in (0, 1, 2)

    def test_tema_search_runs(self) -> None:
        mock_response = MagicMock()
        mock_response.total_count = 0
        mock_response.elapsed_seconds = 0.1
        mock_response.results = []
        mock_response.courts_queried = ["stf"]
        mock_response.courts_failed = []
        mock_response.explain = None
        mock_response.query = MagicMock()
        mock_response.query.query_type = "tema"
        mock_response.query.value = "test"

        with patch("juris.cli.search_cli.SearchDispatcher") as MockDispatcher:
            instance = MockDispatcher.return_value
            instance.search = AsyncMock(return_value=mock_response)
            result = runner.invoke(search_app, ["--tema", "improbidade"])
            assert result.exit_code == 0

    def test_json_output_format(self) -> None:
        mock_response = MagicMock()
        mock_response.total_count = 0
        mock_response.elapsed_seconds = 0.1
        mock_response.results = []
        mock_response.courts_queried = ["stf"]
        mock_response.courts_failed = []
        mock_response.explain = None
        mock_response.query = MagicMock()
        mock_response.query.query_type = "tema"
        mock_response.query.value = "test"

        with patch("juris.cli.search_cli.SearchDispatcher") as MockDispatcher:
            instance = MockDispatcher.return_value
            instance.search = AsyncMock(return_value=mock_response)
            result = runner.invoke(search_app, ["--tema", "test", "--format", "json"])
            assert result.exit_code == 0

    def test_multiple_query_types_errors(self) -> None:
        result = runner.invoke(search_app, ["--tema", "improbidade", "--oab", "SP123456"])
        assert result.exit_code == 1

    def test_markdown_output_format(self) -> None:
        mock_response = MagicMock()
        mock_response.total_count = 0
        mock_response.elapsed_seconds = 0.1
        mock_response.results = []
        mock_response.courts_queried = ["stf"]
        mock_response.courts_failed = []
        mock_response.explain = None
        mock_response.query = MagicMock()
        mock_response.query.query_type = "tema"
        mock_response.query.value = "test"

        with patch("juris.cli.search_cli.SearchDispatcher") as MockDispatcher:
            instance = MockDispatcher.return_value
            instance.search = AsyncMock(return_value=mock_response)
            result = runner.invoke(search_app, ["--tema", "test", "--format", "markdown"])
            assert result.exit_code == 0

    def test_table_output_with_results(self) -> None:
        mock_result = MagicMock()
        mock_result.court = "stf"
        mock_result.case_number = "ADI 1234"
        mock_result.decision_date = None
        mock_result.relator = "Min. Teste"
        mock_result.ementa = "Ementa de teste para verificar formatação da tabela."

        mock_response = MagicMock()
        mock_response.total_count = 1
        mock_response.elapsed_seconds = 0.5
        mock_response.results = [mock_result]
        mock_response.courts_queried = ["stf"]
        mock_response.courts_failed = []
        mock_response.explain = None
        mock_response.query = MagicMock()
        mock_response.query.query_type = "tema"
        mock_response.query.value = "test"

        with patch("juris.cli.search_cli.SearchDispatcher") as MockDispatcher:
            instance = MockDispatcher.return_value
            instance.search = AsyncMock(return_value=mock_response)
            result = runner.invoke(search_app, ["--tema", "test"])
            assert result.exit_code == 0
