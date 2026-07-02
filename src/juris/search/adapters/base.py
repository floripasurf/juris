"""Base class for court search adapters."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from juris.core.sanitize import safe_error_text
from juris.search.models import QueryType, SearchQuery, SearchResult


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    """Result of an adapter health check.

    Attributes:
        court: Court code identifying the adapter.
        healthy: Whether the adapter responded successfully.
        latency_ms: Round-trip time in milliseconds.
        error: Error message if unhealthy, otherwise None.
    """

    court: str
    healthy: bool
    latency_ms: float
    error: str | None = None


class SearchAdapter(ABC):
    """Abstract base class for jurisprudence portal adapters.

    Each concrete subclass targets one court portal (e.g. TJSP eSAJ,
    TRF1 eProc). Subclasses must declare the class variables below and
    implement :meth:`search`.

    Class variables:
        court_code: Short, unique court identifier (e.g. ``"tjsp"``).
        portal_url: Base URL of the court portal.
        rate_limit_seconds: Minimum seconds between requests (default 2.0).
        supported_query_types: Set of :class:`QueryType` values this adapter accepts.
        user_agent: HTTP User-Agent header sent to the portal.
    """

    court_code: ClassVar[str]
    portal_url: ClassVar[str]
    rate_limit_seconds: ClassVar[float] = 2.0
    supported_query_types: ClassVar[set[QueryType]]
    user_agent: ClassVar[str] = "Juris/1.0 (legal research tool; contact@example.com)"

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Execute a search against the court portal.

        Implementations must handle errors gracefully: catch all exceptions
        internally and return an empty list rather than re-raising.

        Args:
            query: Structured search parameters.

        Returns:
            List of results, possibly empty.
        """

    async def health_check(self) -> HealthCheckResult:
        """Probe the adapter with a minimal search to assess reachability.

        Uses :meth:`search` with a lightweight query so the same error-handling
        path is exercised. Returns :class:`HealthCheckResult` regardless of
        outcome — never raises.

        Returns:
            Health status with latency and optional error message.
        """
        start = time.monotonic()
        try:
            q = SearchQuery(query_type="tema", value="teste", max_results_per_court=1)
            await self.search(q)
            latency = (time.monotonic() - start) * 1000
            return HealthCheckResult(court=self.court_code, healthy=True, latency_ms=latency)
        except Exception as e:  # noqa: BLE001
            latency = (time.monotonic() - start) * 1000
            return HealthCheckResult(
                court=self.court_code,
                healthy=False,
                latency_ms=latency,
                error=safe_error_text(e),
            )

    def supports(self, query_type: QueryType) -> bool:
        """Return True if this adapter can handle the given query type.

        Args:
            query_type: The type of query to check.

        Returns:
            True when ``query_type`` is in :attr:`supported_query_types`.
        """
        return query_type in self.supported_query_types
