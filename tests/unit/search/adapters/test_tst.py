"""Unit tests for the TST adapter."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.tst import TSTAdapter
from juris.search.models import SearchQuery

_FIXTURE = Path("data/search-fixtures/tst_tema_sample.json")


def _mock_client_returning(payload: dict) -> AsyncMock:
    """Build an AsyncMock httpx client whose POST returns the given JSON."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
class TestTSTAdapter:
    """Tests for :class:`TSTAdapter`."""

    async def test_tema_search_returns_correct_count(self) -> None:
        """Two fixture items produce two SearchResult objects."""
        payload = json.loads(_FIXTURE.read_text())
        mock_client = _mock_client_returning(payload)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert len(results) == 2

    async def test_search_posts_to_backend_with_tipos(self) -> None:
        """The request POSTs a body whose tipos array is non-empty.

        The backend silently ignores all filters when ``tipos`` is empty,
        so an empty array would return the entire corpus.
        """
        payload = json.loads(_FIXTURE.read_text())
        mock_client = _mock_client_returning(payload)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            await adapter.search(q)

        call = mock_client.post.call_args
        url = call.args[0] if call.args else call.kwargs.get("url", "")
        body = call.kwargs["json"]
        assert "jurisprudencia-backend2.tst.jus.br/rest/pesquisa-textual" in url
        assert body["e"] == "improbidade administrativa"
        assert len(body["tipos"]) > 0
        assert body["tipos"][0]["codigo"] == "ACORDAO"

    async def test_tema_search_first_result_fields(self) -> None:
        """First result has the expected field values from the fixture."""
        payload = json.loads(_FIXTURE.read_text())
        mock_client = _mock_client_returning(payload)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[0]
        assert r.court == "tst"
        assert r.case_number == "RRAg - 2093-21.2017.5.09.0015"
        assert r.relator == "evandro pereira valadao lopes"
        assert r.decision_date == date(2026, 5, 13)
        assert r.classe == "RRAg"
        assert r.cnj_number == "0002093-21.2017.5.09.0015"
        assert r.url == ("https://jurisprudencia.tst.jus.br/#/detalhe-documento/c8f563ad1a64a28e97620072b1b6cf6")
        assert r.ementa is not None
        assert len(r.ementa) > 0

    async def test_tema_search_second_result_fields(self) -> None:
        """Second result has the expected field values from the fixture."""
        payload = json.loads(_FIXTURE.read_text())
        mock_client = _mock_client_returning(payload)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[1]
        assert r.court == "tst"
        assert r.case_number == "Ag-AIRR - 643-04.2020.5.07.0012"
        assert r.relator == "alexandre de souza agra belmonte"
        assert r.decision_date == date(2026, 5, 28)
        assert r.classe == "Ag"
        assert r.cnj_number == "0000643-04.2020.5.07.0012"

    async def test_null_ementa_falls_back_to_highlight(self) -> None:
        """A null ementa field falls back to txtEmentaHighlight without raising."""
        payload = json.loads(_FIXTURE.read_text())
        reg = payload["registros"][0]["registro"]
        reg["ementa"] = None
        reg["txtEmentaHighlight"] = "<p>EMENTA DE TESTE</p>"
        mock_client = _mock_client_returning(payload)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="teste")
            results = await adapter.search(q)

        assert results[0].ementa == "EMENTA DE TESTE"

    async def test_http_error_returns_empty_list(self) -> None:
        """Network errors are swallowed and an empty list is returned."""
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("timeout"))

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = TSTAdapter()
            q = SearchQuery(query_type="tema", value="teste")
            results = await adapter.search(q)

        assert results == []

    async def test_result_source_query_set_correctly(self) -> None:
        """The source_query field on each result matches the query passed in."""
        payload = json.loads(_FIXTURE.read_text())
        mock_client = _mock_client_returning(payload)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
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
