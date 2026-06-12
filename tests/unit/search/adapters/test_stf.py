"""Unit tests for the STF adapter."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from juris.search.adapters.stf import STFAdapter
from juris.search.models import SearchQuery


@pytest.mark.asyncio
class TestSTFAdapter:
    """Tests for :class:`STFAdapter`."""

    async def test_tema_search_returns_correct_count(self) -> None:
        """Two fixture results produce two SearchResult objects."""
        fixture = Path("data/search-fixtures/stf_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STFAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert len(results) == 2

    async def test_tema_search_first_result_fields(self) -> None:
        """First result has the expected field values from the fixture."""
        fixture = Path("data/search-fixtures/stf_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STFAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[0]
        assert r.court == "stf"
        assert r.case_number == "RE 852475"
        assert r.relator == "Min. Alexandre de Moraes"
        assert r.decision_date == date(2024, 6, 15)
        assert r.classe == "RE"
        assert r.url == "https://portal.stf.jus.br/processos/detalhe.asp?incidente=12345"
        assert r.ementa is not None
        assert len(r.ementa) > 0

    async def test_tema_search_second_result_fields(self) -> None:
        """Second result has the expected field values from the fixture."""
        fixture = Path("data/search-fixtures/stf_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STFAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[1]
        assert r.court == "stf"
        assert r.case_number == "ADI 7042"
        assert r.relator == "Min. Luís Roberto Barroso"
        assert r.decision_date == date(2024, 3, 10)
        assert r.classe == "ADI"
        assert r.url == "https://portal.stf.jus.br/processos/detalhe.asp?incidente=67890"

    async def test_http_error_returns_empty_list(self) -> None:
        """Network errors are swallowed and an empty list is returned."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))  # top-level import

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STFAdapter()
            q = SearchQuery(query_type="tema", value="teste")
            results = await adapter.search(q)

        assert results == []

    async def test_result_source_query_set_correctly(self) -> None:
        """The source_query field on each result matches the query passed in."""
        fixture = Path("data/search-fixtures/stf_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STFAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert all(r.source_query is q for r in results)

    async def test_adapter_metadata(self) -> None:
        """Adapter class variables are set to the expected values."""
        adapter = STFAdapter()
        assert adapter.court_code == "stf"
        assert adapter.portal_url == "https://jurisprudencia.stf.jus.br"
        assert "tema" in adapter.supported_query_types
