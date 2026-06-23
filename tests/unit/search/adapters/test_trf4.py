"""Tests for TRF4 search adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.trf4 import TRF4Adapter
from juris.search.models import SearchQuery

_MINIMAL_HTML = """
<html><body>
<table>
  <tbody>
    <tr>
      <td><a href="/pesquisa/doc?id=789">APELAÇÃO CÍVEL<br/>5005555-66.2020.4.04.7100</a></td>
      <td>15/07/2023</td>
      <td>Des. Fed. ANA COSTA</td>
      <td>TRIBUTÁRIO. ICMS. CREDITAMENTO. POSSIBILIDADE. REFORMA DA SENTENÇA.</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


@pytest.fixture()
def adapter() -> TRF4Adapter:
    return TRF4Adapter()


@pytest.fixture()
def query() -> SearchQuery:
    return SearchQuery(query_type="tema", value="tributário", max_results_per_court=10)


class TestTRF4AdapterMeta:
    def test_court_code(self, adapter: TRF4Adapter) -> None:
        assert adapter.court_code == "trf4"

    def test_supports_tema(self, adapter: TRF4Adapter) -> None:
        assert adapter.supports("tema")

    def test_does_not_support_cnpj(self, adapter: TRF4Adapter) -> None:
        assert not adapter.supports("cnpj")

    def test_rate_limit(self, adapter: TRF4Adapter) -> None:
        assert adapter.rate_limit_seconds == 2.0

    def test_portal_url_contains_trf4(self, adapter: TRF4Adapter) -> None:
        assert "trf4.jus.br" in adapter.portal_url


class TestTRF4AdapterParse:
    def test_parse_returns_results(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert len(results) == 1

    def test_parse_case_number(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].case_number == "5005555-66.2020.4.04.7100"

    def test_parse_cnj_normalized(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].cnj_number == "5005555-66.2020.4.04.7100"

    def test_parse_decision_date(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        from datetime import date

        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].decision_date == date(2023, 7, 15)

    def test_parse_ementa_not_empty(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert "TRIBUTÁRIO" in results[0].ementa

    def test_parse_url_prefixed(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].url.startswith("https://jurisprudencia.trf4.jus.br")

    def test_parse_court(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].court == "trf4"

    def test_parse_empty_returns_empty(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        results = adapter._parse("<html><body></body></html>", query)
        assert results == []

    def test_parse_respects_max_results(self, adapter: TRF4Adapter) -> None:
        q = SearchQuery(query_type="tema", value="teste", max_results_per_court=1)
        multi_rows = """
        <html><body><table><tbody>
          <tr><td><a href="/a">5001111-22.2021.4.04.7100</a></td><td>01/01/2023</td><td>R1</td><td>E1</td></tr>
          <tr><td><a href="/b">5002222-33.2022.4.04.7100</a></td><td>02/01/2023</td><td>R2</td><td>E2</td></tr>
        </tbody></table></body></html>
        """
        results = adapter._parse(multi_rows, q)
        assert len(results) == 1


@pytest.mark.asyncio()
class TestTRF4AdapterSearch:
    async def test_search_unsupported_type_returns_empty(self, adapter: TRF4Adapter) -> None:
        q = SearchQuery(query_type="oab", value="MG99999")
        results = await adapter.search(q)
        assert results == []

    async def test_search_http_error_returns_empty(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("server error")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert results == []

    async def test_search_returns_parsed_results(self, adapter: TRF4Adapter, query: SearchQuery) -> None:
        mock_resp = MagicMock()
        mock_resp.text = _MINIMAL_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert len(results) == 1
        assert results[0].court == "trf4"
