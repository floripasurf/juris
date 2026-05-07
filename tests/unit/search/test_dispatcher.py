"""Tests for SearchDispatcher — fanout, dedup, ranking, explain."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from juris.search.models import SearchQuery, SearchResult, SearchResponse
from juris.search.rate_limiter import CourtRateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_query(query_type: str = "tema", value: str = "improbidade") -> SearchQuery:
    return SearchQuery(query_type=query_type, value=value)  # type: ignore[arg-type]


def _make_result(
    court: str,
    case_number: str = "RE 1",
    cnj_number: str | None = None,
) -> SearchResult:
    q = _make_query()
    return SearchResult(
        court=court,
        case_number=case_number,
        cnj_number=cnj_number,
        decision_date=date(2024, 1, 1),
        relator="Min. Fulano",
        classe="RE",
        ementa="improbidade administrativa comprovada",
        url=f"https://{court}.jus.br/1",
        source_query=q,
        fetched_at=datetime(2024, 7, 1, 10, 0, 0),
    )


# ---------------------------------------------------------------------------
# Mock adapters
# ---------------------------------------------------------------------------

class _MockAdapter:
    """Minimal concrete adapter — not a subclass of SearchAdapter so we avoid
    ABC enforcement; the dispatcher only calls .supports() and .search()."""

    def __init__(
        self,
        court_code: str,
        results: list[SearchResult],
        supported_types: set[str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.court_code = court_code
        self._results = results
        self._supported = supported_types or {"tema", "oab", "nome", "cpf", "cnpj", "cnj"}
        self._raises = raises

    def supports(self, query_type: str) -> bool:
        return query_type in self._supported

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        if self._raises is not None:
            raise self._raises
        return self._results


def _zero_limiter(tmp_path: Path) -> CourtRateLimiter:
    """Rate limiter with zero-second interval so tests are fast."""
    return CourtRateLimiter(default_interval=0.0, state_file=tmp_path / "rl.json")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSearchDispatcher:
    async def test_fanout_to_multiple_adapters(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        r1 = _make_result("stf", case_number="STF-1")
        r2 = _make_result("stj", case_number="STJ-1")
        adapters = {
            "stf": _MockAdapter("stf", [r1]),
            "stj": _MockAdapter("stj", [r2]),
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query())

        assert response.total_count == 2
        case_numbers = {r.case_number for r in response.results}
        assert case_numbers == {"STF-1", "STJ-1"}
        assert set(response.courts_queried) == {"stf", "stj"}

    async def test_unsupported_query_type_skipped(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        r1 = _make_result("stf", case_number="STF-1")
        adapters = {
            "stf": _MockAdapter("stf", [r1], supported_types={"tema"}),
            "stj": _MockAdapter("stj", [], supported_types={"oab"}),  # does not support "tema"
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query(query_type="tema"))

        assert response.total_count == 1
        assert "stf" in response.courts_queried
        assert "stj" not in response.courts_queried

    async def test_adapter_error_partial_results(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        r1 = _make_result("stf", case_number="STF-1")
        adapters = {
            "stf": _MockAdapter("stf", [r1]),
            "stj": _MockAdapter("stj", [], raises=RuntimeError("portal down")),
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query())

        assert response.total_count == 1
        failed_courts = [c for c, _ in response.courts_failed]
        assert "stj" in failed_courts

    async def test_cnj_dedup_cross_court(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        # Same CNJ from two different courts — should deduplicate to 1.
        shared_cnj = "0001234-56.2024.8.26.0100"
        r_stf = _make_result("stf", case_number="STF-42", cnj_number=shared_cnj)
        r_stj = _make_result("stj", case_number="STJ-99", cnj_number=shared_cnj)
        adapters = {
            "stf": _MockAdapter("stf", [r_stf]),
            "stj": _MockAdapter("stj", [r_stj]),
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query())

        assert response.total_count == 1

    async def test_court_case_dedup_fallback(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        # Same (court, case_number), no CNJ — should deduplicate to 1.
        r1 = _make_result("stf", case_number="RE-999", cnj_number=None)
        r2 = _make_result("stf", case_number="RE-999", cnj_number=None)
        adapters = {
            "stf": _MockAdapter("stf", [r1]),
            "stj": _MockAdapter("stj", [r2]),
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query())

        assert response.total_count == 1

    async def test_unknown_court_in_filter(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        adapters = {
            "stf": _MockAdapter("stf", [_make_result("stf")]),
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query(), courts=["invalid"])

        assert response.total_count == 0
        failed_courts = [c for c, _ in response.courts_failed]
        assert "invalid" in failed_courts

    async def test_elapsed_tracked(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        adapters = {"stf": _MockAdapter("stf", [_make_result("stf")])}
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query())

        assert response.elapsed_seconds >= 0.0

    async def test_explain_populated(self, tmp_path: Path) -> None:
        from juris.search.dispatcher import SearchDispatcher

        r1 = _make_result("stf")
        adapters = {
            "stf": _MockAdapter("stf", [r1], supported_types={"tema"}),
            "stj": _MockAdapter("stj", [], supported_types={"oab"}),
        }
        dispatcher = SearchDispatcher(adapters=adapters, rate_limiter=_zero_limiter(tmp_path))
        response = await dispatcher.search(_make_query(query_type="tema"), explain=True)

        assert response.explain is not None
        assert "stf" in response.explain.per_court_latency
        assert "stj" not in response.explain.per_court_latency
        skipped_courts = [c for c, _ in response.explain.courts_skipped]
        assert "stj" in skipped_courts
        assert response.explain.dedup_removed >= 0
