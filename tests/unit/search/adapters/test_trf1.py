"""Tests for TRF1 search adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.trf1 import TRF1Adapter
from juris.search.models import SearchQuery

_MINIMAL_HTML = """
<html><body>
<table>
  <tbody>
    <tr>
      <td><a href="/sjur/documento?id=123">APELAÇÃO CÍVEL<br/>5001111-22.2021.4.01.3400</a></td>
      <td>10/05/2023</td>
      <td>Des. Fed. JOÃO SILVA</td>
      <td>ADMINISTRATIVO. IMPROBIDADE. CONFIGURAÇÃO. APELAÇÃO PROVIDA.</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


@pytest.fixture()
def adapter() -> TRF1Adapter:
    return TRF1Adapter()


@pytest.fixture()
def query() -> SearchQuery:
    return SearchQuery(query_type="tema", value="improbidade", max_results_per_court=10)


class TestTRF1AdapterMeta:
    def test_court_code(self, adapter: TRF1Adapter) -> None:
        assert adapter.court_code == "trf1"

    def test_supports_tema(self, adapter: TRF1Adapter) -> None:
        assert adapter.supports("tema")

    def test_does_not_support_oab(self, adapter: TRF1Adapter) -> None:
        assert not adapter.supports("oab")

    def test_rate_limit(self, adapter: TRF1Adapter) -> None:
        assert adapter.rate_limit_seconds == 2.0


class TestTRF1AdapterParse:
    def test_parse_returns_results(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert len(results) == 1

    def test_parse_case_number(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].case_number == "5001111-22.2021.4.01.3400"

    def test_parse_cnj_normalized(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].cnj_number == "5001111-22.2021.4.01.3400"

    def test_parse_decision_date(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        from datetime import date

        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].decision_date == date(2023, 5, 10)

    def test_parse_relator(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].relator == "Des. Fed. JOÃO SILVA"

    def test_parse_ementa_not_empty(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert "IMPROBIDADE" in results[0].ementa

    def test_parse_url_prefixed(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].url.startswith("https://trf1.jus.br")

    def test_parse_court(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse(_MINIMAL_HTML, query)
        assert results[0].court == "trf1"

    def test_parse_empty_table(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse("<html><body><table></table></body></html>", query)
        assert results == []

    def test_parse_no_table(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        results = adapter._parse("<html><body><p>sem resultados</p></body></html>", query)
        assert results == []

    def test_parse_respects_max_results(self, adapter: TRF1Adapter) -> None:
        q = SearchQuery(query_type="tema", value="teste", max_results_per_court=1)
        multi_rows = """
        <html><body><table><tbody>
          <tr><td><a href="/a">5001111-22.2021.4.01.3400</a></td><td>01/01/2023</td><td>R1</td><td>E1</td></tr>
          <tr><td><a href="/b">5002222-33.2021.4.01.3400</a></td><td>02/01/2023</td><td>R2</td><td>E2</td></tr>
        </tbody></table></body></html>
        """
        results = adapter._parse(multi_rows, q)
        assert len(results) == 1


@pytest.mark.asyncio()
class TestTRF1AdapterSearch:
    async def test_search_unsupported_type_returns_empty(self, adapter: TRF1Adapter) -> None:
        q = SearchQuery(query_type="oab", value="SP12345")
        results = await adapter.search(q)
        assert results == []

    async def test_search_http_error_returns_empty(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("connection error")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert results == []

    async def test_search_returns_parsed_results(self, adapter: TRF1Adapter, query: SearchQuery) -> None:
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
        assert results[0].court == "trf1"
