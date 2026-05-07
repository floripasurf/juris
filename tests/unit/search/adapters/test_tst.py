"""Unit tests for the TST adapter."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.tst import TSTAdapter
from juris.search.models import SearchQuery


@pytest.mark.asyncio
class TestTSTAdapter:
    """Tests for :class:`TSTAdapter`."""

    async def test_tema_search_returns_correct_count(self) -> None:
        """Two fixture items produce two SearchResult objects."""
        fixture = Path("data/search-fixtures/tst_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.adapters.tst.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert len(results) == 2

    async def test_tema_search_first_result_fields(self) -> None:
        """First result has the expected field values from the fixture."""
        fixture = Path("data/search-fixtures/tst_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.adapters.tst.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[0]
        assert r.court == "tst"
        assert r.case_number == "RR-10014-28.2019.5.03.0097"
        assert r.relator == "Min. Mauricio Godinho Delgado"
        assert r.decision_date == date(2024, 5, 22)
        assert r.classe == "RR"
        assert r.url == "https://jurisprudencia.tst.jus.br/processos/detalhe/TST-RR-10014-28.2019.5.03.0097"
        assert r.ementa is not None
        assert len(r.ementa) > 0

    async def test_tema_search_second_result_fields(self) -> None:
        """Second result has the expected field values from the fixture."""
        fixture = Path("data/search-fixtures/tst_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.adapters.tst.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[1]
        assert r.court == "tst"
        assert r.case_number == "AIRR-20082-55.2021.5.04.0121"
        assert r.relator == "Min. Alexandre Luiz Ramos"
        assert r.decision_date == date(2024, 2, 14)
        assert r.classe == "AIRR"
        assert r.url == "https://jurisprudencia.tst.jus.br/processos/detalhe/TST-AIRR-20082-55.2021.5.04.0121"

    async def test_http_error_returns_empty_list(self) -> None:
        """Network errors are swallowed and an empty list is returned."""
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("timeout"))

        with patch("juris.search.adapters.tst.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="teste")
            results = await adapter.search(q)

        assert results == []

    async def test_result_source_query_set_correctly(self) -> None:
        """The source_query field on each result matches the query passed in."""
        fixture = Path("data/search-fixtures/tst_tema_sample.json").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = json.loads(fixture)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.adapters.tst.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert all(r.source_query is q for r in results)

    async def test_adapter_metadata(self) -> None:
        """Adapter class variables are set to the expected values."""
        adapter = TSTAdapter()
        assert adapter.court_code == "tst"
        assert adapter.portal_url == "https://jurisprudencia.tst.jus.br"
        assert "tema" in adapter.supported_query_types
