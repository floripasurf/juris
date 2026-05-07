"""Tests for unified multi-court search data models."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from juris.search.models import (
    SearchExplain,
    SearchQuery,
    SearchResponse,
    SearchResult,
)


class TestSearchQuery:
    """Tests for SearchQuery value object."""

    def test_create_tema_query(self) -> None:
        query = SearchQuery(query_type="tema", value="responsabilidade civil")
        assert query.query_type == "tema"
        assert query.value == "responsabilidade civil"
        assert query.date_range is None
        assert query.max_results_per_court == 20

    def test_create_oab_query(self) -> None:
        query = SearchQuery(query_type="oab", value="123456/SP")
        assert query.query_type == "oab"
        assert query.value == "123456/SP"

    def test_create_nome_query(self) -> None:
        query = SearchQuery(query_type="nome", value="João da Silva")
        assert query.query_type == "nome"

    def test_create_cpf_query(self) -> None:
        query = SearchQuery(query_type="cpf", value="123.456.789-00")
        assert query.query_type == "cpf"

    def test_create_cnpj_query(self) -> None:
        query = SearchQuery(query_type="cnpj", value="12.345.678/0001-90")
        assert query.query_type == "cnpj"

    def test_create_cnj_query(self) -> None:
        query = SearchQuery(query_type="cnj", value="0001234-56.2023.8.26.0001")
        assert query.query_type == "cnj"

    def test_date_range(self) -> None:
        start = date(2023, 1, 1)
        end = date(2023, 12, 31)
        query = SearchQuery(
            query_type="tema",
            value="dano moral",
            date_range=(start, end),
        )
        assert query.date_range == (start, end)
        assert query.date_range[0] == start
        assert query.date_range[1] == end

    def test_custom_max_results(self) -> None:
        query = SearchQuery(query_type="oab", value="SP123456", max_results_per_court=50)
        assert query.max_results_per_court == 50

    def test_frozen(self) -> None:
        query = SearchQuery(query_type="tema", value="prescrição")
        with pytest.raises(AttributeError):
            query.value = "outro"  # type: ignore[misc]


class TestSearchResult:
    """Tests for SearchResult value object."""

    def _make_query(self) -> SearchQuery:
        return SearchQuery(query_type="tema", value="dano moral")

    def test_create_result(self) -> None:
        query = self._make_query()
        fetched = datetime(2024, 5, 1, 12, 0, 0)
        result = SearchResult(
            court="TJSP",
            case_number="1234567-89.2023.8.26.0001",
            cnj_number="1234567-89.2023.8.26.0001",
            decision_date=date(2024, 4, 15),
            relator="Des. João Pereira",
            classe="Apelação Cível",
            ementa="Responsabilidade civil. Dano moral configurado.",
            url="https://esaj.tjsp.jus.br/cgi-bin/XXXXX",
            source_query=query,
            fetched_at=fetched,
        )
        assert result.court == "TJSP"
        assert result.case_number == "1234567-89.2023.8.26.0001"
        assert result.cnj_number == "1234567-89.2023.8.26.0001"
        assert result.decision_date == date(2024, 4, 15)
        assert result.relator == "Des. João Pereira"
        assert result.classe == "Apelação Cível"
        assert result.ementa == "Responsabilidade civil. Dano moral configurado."
        assert result.source_query is query
        assert result.fetched_at == fetched

    def test_none_optional_fields(self) -> None:
        query = self._make_query()
        result = SearchResult(
            court="STJ",
            case_number="REsp 1234567/SP",
            cnj_number=None,
            decision_date=None,
            relator=None,
            classe=None,
            ementa="Ementa do acórdão.",
            url="https://stj.jus.br/processo/1234567",
            source_query=query,
            fetched_at=datetime(2024, 5, 1, 0, 0, 0),
        )
        assert result.cnj_number is None
        assert result.decision_date is None
        assert result.relator is None
        assert result.classe is None

    def test_frozen(self) -> None:
        query = self._make_query()
        result = SearchResult(
            court="STF",
            case_number="RE 123456",
            cnj_number=None,
            decision_date=None,
            relator=None,
            classe=None,
            ementa="Ementa.",
            url="https://stf.jus.br/re123456",
            source_query=query,
            fetched_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        with pytest.raises(AttributeError):
            result.court = "TJRJ"  # type: ignore[misc]


class TestSearchResponse:
    """Tests for SearchResponse value object."""

    def _make_query(self) -> SearchQuery:
        return SearchQuery(query_type="oab", value="SP12345")

    def test_create_response_empty_results(self) -> None:
        query = self._make_query()
        response = SearchResponse(
            query=query,
            results=[],
            courts_queried=["TJSP", "STJ"],
            courts_failed=[],
            total_count=0,
            elapsed_seconds=1.23,
        )
        assert response.query is query
        assert response.results == []
        assert response.courts_queried == ["TJSP", "STJ"]
        assert response.courts_failed == []
        assert response.total_count == 0
        assert response.elapsed_seconds == 1.23
        assert response.explain is None

    def test_create_response_with_failures(self) -> None:
        query = self._make_query()
        response = SearchResponse(
            query=query,
            results=[],
            courts_queried=["TJSP", "TJRJ", "STJ"],
            courts_failed=[("TJRJ", "timeout"), ("STJ", "503 Service Unavailable")],
            total_count=0,
            elapsed_seconds=5.0,
        )
        assert len(response.courts_failed) == 2
        assert response.courts_failed[0] == ("TJRJ", "timeout")
        assert response.courts_failed[1] == ("STJ", "503 Service Unavailable")

    def test_create_response_with_explain(self) -> None:
        query = self._make_query()
        explain = SearchExplain(
            courts_requested=["TJSP", "STJ"],
            courts_skipped=[("TJAM", "not supported")],
            per_court_latency={"TJSP": 0.8, "STJ": 1.2},
            ranking_weights={"recency": 0.5, "relevance": 0.5},
            dedup_removed=3,
        )
        response = SearchResponse(
            query=query,
            results=[],
            courts_queried=["TJSP", "STJ"],
            courts_failed=[],
            total_count=0,
            elapsed_seconds=2.0,
            explain=explain,
        )
        assert response.explain is explain
        assert response.explain.dedup_removed == 3

    def test_frozen(self) -> None:
        query = self._make_query()
        response = SearchResponse(
            query=query,
            results=[],
            courts_queried=[],
            courts_failed=[],
            total_count=0,
            elapsed_seconds=0.1,
        )
        with pytest.raises(AttributeError):
            response.total_count = 99  # type: ignore[misc]


class TestSearchExplain:
    """Tests for SearchExplain value object."""

    def test_create_explain(self) -> None:
        explain = SearchExplain(
            courts_requested=["TJSP", "STJ", "STF"],
            courts_skipped=[("TJAM", "adapter not implemented")],
            per_court_latency={"TJSP": 0.5, "STJ": 1.1, "STF": 0.9},
            ranking_weights={"recency": 0.4, "relevance": 0.6},
            dedup_removed=5,
        )
        assert explain.courts_requested == ["TJSP", "STJ", "STF"]
        assert explain.courts_skipped == [("TJAM", "adapter not implemented")]
        assert explain.per_court_latency["TJSP"] == 0.5
        assert explain.ranking_weights["relevance"] == 0.6
        assert explain.dedup_removed == 5

    def test_frozen(self) -> None:
        explain = SearchExplain(
            courts_requested=[],
            courts_skipped=[],
            per_court_latency={},
            ranking_weights={},
            dedup_removed=0,
        )
        with pytest.raises(AttributeError):
            explain.dedup_removed = 10  # type: ignore[misc]
