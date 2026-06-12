"""Tests for cross-court ranking heuristics."""

from __future__ import annotations

from datetime import date, datetime

from juris.search.models import SearchQuery, SearchResult
from juris.search.ranking import rank_results


def _make_result(
    court: str,
    decision_date: date | None = None,
    ementa: str = "ementa genérica",
    case_number: str = "RE 123",
) -> SearchResult:
    q = SearchQuery(query_type="tema", value="improbidade administrativa")
    return SearchResult(
        court=court,
        case_number=case_number,
        cnj_number=None,
        decision_date=decision_date,
        relator="Min. Fulano",
        classe="RE",
        ementa=ementa,
        url=f"https://{court}.jus.br/...",
        source_query=q,
        fetched_at=datetime(2024, 7, 1, 10, 0, 0),
    )


class TestRankResults:
    def test_empty_list(self) -> None:
        q = SearchQuery(query_type="tema", value="test")
        assert rank_results([], q) == []

    def test_stf_ranks_above_trf(self) -> None:
        stf = _make_result("stf", date(2024, 1, 1))
        trf3 = _make_result("trf3", date(2024, 1, 1))
        ranked = rank_results([trf3, stf], SearchQuery(query_type="tema", value="test"))
        assert ranked[0].court == "stf"

    def test_stj_ranks_above_trf(self) -> None:
        stj = _make_result("stj", date(2024, 1, 1))
        trf1 = _make_result("trf1", date(2024, 1, 1))
        ranked = rank_results([trf1, stj], SearchQuery(query_type="tema", value="test"))
        assert ranked[0].court == "stj"

    def test_tst_ranks_above_trt(self) -> None:
        tst = _make_result("tst", date(2024, 1, 1))
        trt2 = _make_result("trt2", date(2024, 1, 1))
        ranked = rank_results([trt2, tst], SearchQuery(query_type="tema", value="test"))
        assert ranked[0].court == "tst"

    def test_recency_boosts_ranking(self) -> None:
        old = _make_result("trf3", date(2020, 1, 1))
        recent = _make_result("trf3", date(2024, 6, 1))
        ranked = rank_results([old, recent], SearchQuery(query_type="tema", value="test"))
        assert ranked[0].decision_date == date(2024, 6, 1)

    def test_none_date_sorted_last(self) -> None:
        no_date = _make_result("stf", None)
        with_date = _make_result("trf3", date(2024, 1, 1))
        ranked = rank_results([no_date, with_date], SearchQuery(query_type="tema", value="test"))
        assert ranked[-1].decision_date is None

    def test_term_overlap_boosts(self) -> None:
        exact = _make_result("trf3", date(2024, 1, 1), ementa="improbidade administrativa comprovada")
        partial = _make_result("trf3", date(2024, 1, 1), ementa="questão processual diversa")
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        ranked = rank_results([partial, exact], q)
        assert "improbidade" in ranked[0].ementa.lower()

    def test_hierarchy_order_stf_stj_tst_trf_tj(self) -> None:
        tj = _make_result("tjsp", date(2024, 1, 1))
        trf = _make_result("trf3", date(2024, 1, 1))
        tst = _make_result("tst", date(2024, 1, 1))
        stj = _make_result("stj", date(2024, 1, 1))
        stf = _make_result("stf", date(2024, 1, 1))
        q = SearchQuery(query_type="tema", value="test")
        ranked = rank_results([tj, trf, tst, stj, stf], q)
        courts = [r.court for r in ranked]
        assert courts.index("stf") < courts.index("stj")
        assert courts.index("stj") < courts.index("tst")
        assert courts.index("tst") < courts.index("trf3")
        assert courts.index("trf3") < courts.index("tjsp")
