"""Search dispatcher — parallel fanout, dedup, ranking."""
from __future__ import annotations

import asyncio
import logging
import time

from juris.search.adapters import get_all_adapters
from juris.search.adapters.base import SearchAdapter
from juris.search.models import SearchExplain, SearchQuery, SearchResponse, SearchResult
from juris.search.ranking import rank_results
from juris.search.rate_limiter import CourtRateLimiter

logger = logging.getLogger(__name__)


class SearchDispatcher:
    """Fans out a :class:`SearchQuery` to multiple court adapters in parallel.

    Deduplicates results first by normalized CNJ number (cross-court), then
    by ``(court, case_number)`` for results without a CNJ. Ranks the deduped
    set and returns a :class:`SearchResponse`.

    Args:
        adapters: Mapping of court code → instantiated adapter. If ``None``,
            all adapters discovered by :func:`get_all_adapters` are
            instantiated automatically.
        rate_limiter: Per-court rate limiter. Defaults to
            :class:`CourtRateLimiter` with standard intervals.
    """

    def __init__(
        self,
        adapters: dict[str, SearchAdapter] | None = None,
        rate_limiter: CourtRateLimiter | None = None,
    ) -> None:
        if adapters is not None:
            self._adapters = adapters
        else:
            self._adapters = {code: cls() for code, cls in get_all_adapters().items()}
        self._rate_limiter = rate_limiter or CourtRateLimiter()

    async def search(
        self,
        query: SearchQuery,
        courts: list[str] | None = None,
        explain: bool = False,
    ) -> SearchResponse:
        """Execute a multi-court search and return an aggregated response.

        Args:
            query: Structured search parameters.
            courts: Restrict search to these court codes. ``None`` means all
                registered adapters.
            explain: When ``True``, populate :attr:`SearchResponse.explain`
                with diagnostic metadata.

        Returns:
            :class:`SearchResponse` with ranked, deduplicated results.
        """
        t0 = time.monotonic()

        # Resolve target adapters
        target_courts = courts or list(self._adapters.keys())
        active: dict[str, SearchAdapter] = {}
        skipped: list[tuple[str, str]] = []
        failed: list[tuple[str, str]] = []

        for court in target_courts:
            adapter = self._adapters.get(court)
            if adapter is None:
                failed.append((court, "Unknown court"))
                continue
            if not adapter.supports(query.query_type):
                skipped.append((court, f"Does not support {query.query_type}"))
                continue
            active[court] = adapter

        # Parallel fanout
        per_court_latency: dict[str, float] = {}

        async def _search_one(court: str, adapter: SearchAdapter) -> list[SearchResult]:
            await self._rate_limiter.acquire(court)
            ct0 = time.monotonic()
            try:
                results = await adapter.search(query)
                per_court_latency[court] = time.monotonic() - ct0
                return results
            except Exception as exc:  # noqa: BLE001
                per_court_latency[court] = time.monotonic() - ct0
                failed.append((court, str(exc)))
                logger.warning("Adapter error for court %s: %s", court, exc)
                return []

        tasks = [_search_one(court, adapter) for court, adapter in active.items()]
        results_lists = await asyncio.gather(*tasks)

        all_results: list[SearchResult] = []
        for results in results_lists:
            all_results.extend(results)

        # Dedup
        deduped, dedup_removed = self._dedupe(all_results)

        # Rank
        ranked = rank_results(deduped, query)

        elapsed = time.monotonic() - t0

        explain_data: SearchExplain | None = None
        if explain:
            explain_data = SearchExplain(
                courts_requested=target_courts,
                courts_skipped=skipped,
                per_court_latency=per_court_latency,
                ranking_weights={
                    "court_hierarchy": 0.4,
                    "recency": 0.35,
                    "term_overlap": 0.25,
                },
                dedup_removed=dedup_removed,
            )

        return SearchResponse(
            query=query,
            results=ranked,
            courts_queried=list(active.keys()),
            courts_failed=failed,
            total_count=len(ranked),
            elapsed_seconds=round(elapsed, 3),
            explain=explain_data,
        )

    @staticmethod
    def _dedupe(results: list[SearchResult]) -> tuple[list[SearchResult], int]:
        """Deduplicate results by CNJ number, then by (court, case_number).

        CNJ deduplication is cross-court: the first result for a given
        ``cnj_number`` wins regardless of which court produced it.
        For results without a CNJ, the key is ``(court, case_number)``.

        Args:
            results: Flat list of results from all adapters.

        Returns:
            Tuple of (deduplicated list, number of items removed).
        """
        seen_cnj: set[str] = set()
        seen_court_case: set[tuple[str, str]] = set()
        deduped: list[SearchResult] = []
        removed = 0

        for r in results:
            if r.cnj_number:
                if r.cnj_number in seen_cnj:
                    removed += 1
                    continue
                seen_cnj.add(r.cnj_number)
            else:
                key = (r.court, r.case_number)
                if key in seen_court_case:
                    removed += 1
                    continue
                seen_court_case.add(key)
            deduped.append(r)

        return deduped, removed
