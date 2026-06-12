"""Unit tests for the STJ adapter."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.stj import STJAdapter
from juris.search.models import SearchQuery


@pytest.mark.asyncio
class TestSTJAdapter:
    """Tests for :class:`STJAdapter`."""

    async def test_tema_search_returns_correct_count(self) -> None:
        """Two fixture divResult blocks produce two SearchResult objects."""
        fixture = Path("data/search-fixtures/stj_tema_sample.html").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = fixture
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STJAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert len(results) == 2

    async def test_tema_search_first_result_fields(self) -> None:
        """First result has the expected field values from the HTML fixture."""
        fixture = Path("data/search-fixtures/stj_tema_sample.html").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = fixture
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STJAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[0]
        assert r.court == "stj"
        assert r.case_number == "REsp 2.083.156/SP"
        # "Ministro HERMAN BENJAMIN" -> prefix stripped
        assert r.relator == "HERMAN BENJAMIN"
        assert r.decision_date == date(2024, 3, 19)
        assert r.classe == "REsp"
        assert r.url.startswith("https://scon.stj.jus.br")
        assert r.ementa is not None
        assert len(r.ementa) > 0

    async def test_tema_search_second_result_fields(self) -> None:
        """Second result has the expected field values from the HTML fixture."""
        fixture = Path("data/search-fixtures/stj_tema_sample.html").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = fixture
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STJAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        r = results[1]
        assert r.court == "stj"
        assert r.case_number == "REsp 1.984.988/RJ"
        assert r.relator == "ASSUSETE MAGALHÃES"
        assert r.decision_date == date(2024, 2, 6)
        assert r.classe == "REsp"
        assert r.url.startswith("https://scon.stj.jus.br")

    async def test_http_error_returns_empty_list(self) -> None:
        """Network errors are swallowed and an empty list is returned."""
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("timeout"))

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STJAdapter()
            q = SearchQuery(query_type="tema", value="teste")
            results = await adapter.search(q)

        assert results == []

    async def test_result_source_query_set_correctly(self) -> None:
        """The source_query field on each result matches the query passed in."""
        fixture = Path("data/search-fixtures/stj_tema_sample.html").read_text()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = fixture
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("juris.search.http.httpx.AsyncClient", return_value=mock_client):
            adapter = STJAdapter()
            q = SearchQuery(query_type="tema", value="improbidade administrativa")
            results = await adapter.search(q)

        assert all(r.source_query is q for r in results)

    async def test_adapter_metadata(self) -> None:
        """Adapter class variables are set to the expected values."""
        adapter = STJAdapter()
        assert adapter.court_code == "stj"
        assert adapter.portal_url == "https://scon.stj.jus.br"
        assert "tema" in adapter.supported_query_types
