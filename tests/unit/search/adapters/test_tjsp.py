"""Tests for TJSP search adapter — uses data/search-fixtures/tjsp_tema_sample.html."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.search.adapters.tjsp import TJSPAdapter
from juris.search.models import SearchQuery

_FIXTURE_PATH = Path(__file__).parent.parent.parent.parent.parent / "data" / "search-fixtures" / "tjsp_tema_sample.html"

_VIEWSTATE_PAGE = '<input name="javax.faces.ViewState" value="test_viewstate_token" />'


@pytest.fixture()
def fixture_html() -> str:
    return _FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> TJSPAdapter:
    return TJSPAdapter()


@pytest.fixture()
def query() -> SearchQuery:
    return SearchQuery(query_type="tema", value="improbidade administrativa", max_results_per_court=10)


class TestTJSPAdapterMeta:
    def test_court_code(self, adapter: TJSPAdapter) -> None:
        assert adapter.court_code == "tjsp"

    def test_supports_tema(self, adapter: TJSPAdapter) -> None:
        assert adapter.supports("tema")

    def test_does_not_support_oab(self, adapter: TJSPAdapter) -> None:
        assert not adapter.supports("oab")

    def test_rate_limit_is_slower(self, adapter: TJSPAdapter) -> None:
        assert adapter.rate_limit_seconds == 3.0

    def test_portal_url_is_esaj(self, adapter: TJSPAdapter) -> None:
        assert "esaj.tjsp.jus.br" in adapter.portal_url


class TestTJSPExtractViewstate:
    def test_extracts_viewstate(self, adapter: TJSPAdapter) -> None:
        html = '<html><body><input name="javax.faces.ViewState" value="abc123" /></body></html>'
        assert adapter._extract_viewstate(html) == "abc123"

    def test_returns_none_when_missing(self, adapter: TJSPAdapter) -> None:
        assert adapter._extract_viewstate("<html><body></body></html>") is None

    def test_extracts_from_fixture_page(self, adapter: TJSPAdapter, fixture_html: str) -> None:
        # The tjsp fixture itself contains a ViewState input
        vs = adapter._extract_viewstate(fixture_html)
        assert vs == "j_id1:j_id2:j_id3:j_id4:j_id5:j_id6"


class TestTJSPAdapterParseFixture:
    def test_parse_returns_two_results(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert len(results) == 2

    def test_parse_first_case_number(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].case_number == "1023456-78.2020.8.26.0053"

    def test_parse_second_case_number(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[1].case_number == "2048901-33.2019.8.26.0114"

    def test_parse_cnj_normalized_first(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].cnj_number == "1023456-78.2020.8.26.0053"

    def test_parse_decision_date_first(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].decision_date == date(2024, 4, 8)

    def test_parse_decision_date_second(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[1].decision_date == date(2024, 1, 18)

    def test_parse_relator_first(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].relator == "Des. Urbano Ruiz"

    def test_parse_relator_second(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[1].relator == "Des. Osvaldo Magalhães Pinto"

    def test_parse_classe_first(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].classe == "Apelação Cível"

    def test_parse_ementa_contains_keyword(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert "IMPROBIDADE" in results[0].ementa

    def test_parse_url_has_esaj_prefix(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].url.startswith("https://esaj.tjsp.jus.br")

    def test_parse_court_is_tjsp(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        for r in results:
            assert r.court == "tjsp"

    def test_parse_source_query_preserved(self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery) -> None:
        results = adapter._parse(fixture_html, query)
        assert results[0].source_query is query


class TestTJSPAdapterParseEdgeCases:
    def test_parse_no_table_returns_empty(self, adapter: TJSPAdapter, query: SearchQuery) -> None:
        results = adapter._parse("<html><body><p>nenhum resultado</p></body></html>", query)
        assert results == []

    def test_parse_empty_tbody_returns_empty(self, adapter: TJSPAdapter, query: SearchQuery) -> None:
        html = '<table id="tabelaResultados"><tbody></tbody></table>'
        results = adapter._parse(html, query)
        assert results == []

    def test_parse_respects_max_results(self, adapter: TJSPAdapter, fixture_html: str) -> None:
        q = SearchQuery(query_type="tema", value="improbidade", max_results_per_court=1)
        results = adapter._parse(fixture_html, q)
        assert len(results) == 1


@pytest.mark.asyncio()
class TestTJSPAdapterSearch:
    async def test_search_unsupported_type_returns_empty(self, adapter: TJSPAdapter) -> None:
        q = SearchQuery(query_type="cnj", value="1023456-78.2020.8.26.0053")
        results = await adapter.search(q)
        assert results == []

    async def test_search_get_error_returns_empty(self, adapter: TJSPAdapter, query: SearchQuery) -> None:
        mock_get_resp = MagicMock()
        mock_get_resp.raise_for_status.side_effect = Exception("network error")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_get_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert results == []

    async def test_search_post_error_returns_empty(self, adapter: TJSPAdapter, query: SearchQuery) -> None:
        mock_get_resp = MagicMock()
        mock_get_resp.text = _VIEWSTATE_PAGE
        mock_get_resp.raise_for_status = MagicMock()

        mock_post_resp = MagicMock()
        mock_post_resp.raise_for_status.side_effect = Exception("post error")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_get_resp)
            mock_client.post = AsyncMock(return_value=mock_post_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert results == []

    async def test_search_returns_parsed_results(
        self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery
    ) -> None:
        mock_get_resp = MagicMock()
        mock_get_resp.text = _VIEWSTATE_PAGE
        mock_get_resp.raise_for_status = MagicMock()

        mock_post_resp = MagicMock()
        mock_post_resp.text = fixture_html
        mock_post_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_get_resp)
            mock_client.post = AsyncMock(return_value=mock_post_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        assert len(results) == 2
        assert results[0].court == "tjsp"
        assert results[0].case_number == "1023456-78.2020.8.26.0053"

    async def test_search_passes_viewstate_in_post(
        self, adapter: TJSPAdapter, fixture_html: str, query: SearchQuery
    ) -> None:
        mock_get_resp = MagicMock()
        mock_get_resp.text = _VIEWSTATE_PAGE
        mock_get_resp.raise_for_status = MagicMock()

        mock_post_resp = MagicMock()
        mock_post_resp.text = fixture_html
        mock_post_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_get_resp)
            mock_client.post = AsyncMock(return_value=mock_post_resp)
            mock_client_cls.return_value = mock_client

            await adapter.search(query)

        call_kwargs = mock_client.post.call_args
        assert "javax.faces.ViewState" in str(call_kwargs)

    async def test_search_none_viewstate_still_posts(self, adapter: TJSPAdapter, query: SearchQuery) -> None:
        """When ViewState extraction fails, adapter should still attempt POST with empty string."""
        mock_get_resp = MagicMock()
        mock_get_resp.text = "<html><body>no viewstate here</body></html>"
        mock_get_resp.raise_for_status = MagicMock()

        mock_post_resp = MagicMock()
        mock_post_resp.text = "<html><body></body></html>"
        mock_post_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_get_resp)
            mock_client.post = AsyncMock(return_value=mock_post_resp)
            mock_client_cls.return_value = mock_client

            results = await adapter.search(query)

        # POST was still called even without ViewState
        mock_client.post.assert_awaited_once()
        assert results == []
