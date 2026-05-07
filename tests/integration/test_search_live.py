"""Live integration tests for multi-court search.

These tests make real HTTP requests to court portals.
Run with: uv run python -m pytest tests/integration/test_search_live.py -v -m live

NOT run in CI — only for manual verification.
"""
from __future__ import annotations

import pytest

from juris.search.adapters.stf import STFAdapter
from juris.search.adapters.stj import STJAdapter
from juris.search.adapters.tst import TSTAdapter
from juris.search.adapters.trf3 import TRF3Adapter
from juris.search.adapters.tjsp import TJSPAdapter
from juris.search.dispatcher import SearchDispatcher
from juris.search.models import SearchQuery


@pytest.mark.live
@pytest.mark.asyncio
class TestSTFLive:
    async def test_stf_tema_search(self) -> None:
        adapter = STFAdapter()
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        results = await adapter.search(q)
        assert len(results) > 0
        assert all(r.court == "stf" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
class TestSTJLive:
    async def test_stj_tema_search(self) -> None:
        adapter = STJAdapter()
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        results = await adapter.search(q)
        assert len(results) > 0
        assert all(r.court == "stj" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
class TestTSTLive:
    async def test_tst_tema_search(self) -> None:
        adapter = TSTAdapter()
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        results = await adapter.search(q)
        assert len(results) > 0
        assert all(r.court == "tst" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
class TestTRF3Live:
    async def test_trf3_tema_search(self) -> None:
        adapter = TRF3Adapter()
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        results = await adapter.search(q)
        assert len(results) > 0
        assert all(r.court == "trf3" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
class TestTJSPLive:
    async def test_tjsp_tema_search(self) -> None:
        adapter = TJSPAdapter()
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        results = await adapter.search(q)
        assert len(results) > 0
        assert all(r.court == "tjsp" for r in results)


@pytest.mark.live
@pytest.mark.asyncio
class TestDispatcherLive:
    async def test_multi_court_search(self) -> None:
        dispatcher = SearchDispatcher()
        q = SearchQuery(query_type="tema", value="improbidade administrativa")
        response = await dispatcher.search(q, courts=["stf", "stj"])
        assert response.total_count > 0
        assert len(response.courts_queried) > 0

    async def test_explain_mode(self) -> None:
        dispatcher = SearchDispatcher()
        q = SearchQuery(query_type="tema", value="prescrição")
        response = await dispatcher.search(q, courts=["stf"], explain=True)
        assert response.explain is not None
        assert "stf" in response.explain.courts_requested
