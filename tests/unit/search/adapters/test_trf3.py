"""Tests for TRF3 search adapter — uses data/search-fixtures/trf3_tema_sample.html."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.trf3 import TRF3Adapter
from juris.search.models import SearchQuery

_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent.parent.parent
    / "data"
    / "search-fixtures"
    / "trf3_tema_sample.html"
)


@pytest.fixture()
def fixture_html() -> str:
    return _FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> TRF3Adapter:
    return TRF3Adapter()


@pytest.fixture()
def query() -> SearchQuery:
    return SearchQuery(
        query_type="tema", value="improbidade administrativa", max_results_per_court=10
    )


class TestTRF3AdapterMeta:
    def test_court_code(self, adapter: TRF3Adapter) -> None:
        assert adapter.court_code == "trf3"

    def test_supports_tema(self, adapter: TRF3Adapter) -> None:
        assert adapter.supports("tema")

    def test_does_not_support_oab(self, adapter: TRF3Adapter) -> None:
        assert not adapter.supports("oab")

    def test_rate_limit(self, adapter: TRF3Adapter) -> None:
        assert adapter.rate_limit_seconds == 2.0

    def test_portal_url(self, adapter: TRF3Adapter) -> None:
        assert "trf3.jus.br" in adapter.portal_url


class TestTRF3AdapterParseFixture:
    def test_parse_returns_two_results(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert len(results) == 2

    def test_parse_first_case_number(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].case_number == "5001234-56.2020.4.03.6100"

    def test_parse_second_case_number(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[1].case_number == "5009876-12.2018.4.03.6105"

    def test_parse_cnj_number_first(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].cnj_number == "5001234-56.2020.4.03.6100"

    def test_parse_decision_date_first(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].decision_date == date(2024, 4, 12)

    def test_parse_decision_date_second(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[1].decision_date == date(2024, 3, 5)

    def test_parse_relator_strips_prefix(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].relator == "CARLOS MUTA"

    def test_parse_second_relator_strips_prefix(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[1].relator == "MÔNICA NOBRE"

    def test_parse_ementa_contains_keyword(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert "IMPROBIDADE" in results[0].ementa

    def test_parse_url_has_trf3_prefix(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].url.startswith("https://web.trf3.jus.br")

    def test_parse_court_is_trf3(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        for r in results:
            assert r.court == "trf3"

    def test_parse_source_query_preserved(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].source_query is query


class TestTRF3AdapterParseEdgeCases:
    def test_parse_no_table_returns_empty(
        self, adapter: TRF3Adapter, query: SearchQuery
    ) -> None:
        results = adapter._parse("<html><body><p>sem resultados</p></body></html>", query)
        assert results == []

    def test_parse_empty_tbody_returns_empty(
        self, adapter: TRF3Adapter, query: SearchQuery
    ) -> None:
        html = '<table id="tabelaResultado"><tbody></tbody></table>'
        results = adapter._parse(html, query)
        assert results == []

    def test_parse_respects_max_results(
        self, adapter: TRF3Adapter, fixture_html: str
    ) -> None:
        q = SearchQuery(
            query_type="tema", value="improbidade", max_results_per_court=1
        )
        results = adapter._parse(fixture_html, q)
        assert len(results) == 1


@pytest.mark.asyncio()
class TestTRF3AdapterSearch:
    async def test_search_unsupported_type_returns_empty(
        self, adapter: TRF3Adapter
    ) -> None:
        q = SearchQuery(query_type="cnj", value="5001234-56.2020.4.03.6100")
        results = await adapter.search(q)
        assert results == []

    async def test_search_http_error_returns_empty(
        self, adapter: TRF3Adapter, query: SearchQuery
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("connection refused")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert results == []

    async def test_search_returns_parsed_results(
        self, adapter: TRF3Adapter, fixture_html: str, query: SearchQuery
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.text = fixture_html
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert len(results) == 2
        assert results[0].court == "trf3"
        assert results[0].case_number == "5001234-56.2020.4.03.6100"
