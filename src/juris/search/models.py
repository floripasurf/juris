"""Data models for unified multi-court search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

QueryType = Literal["tema", "oab", "nome", "cpf", "cnpj", "cnj"]


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Parameters for a unified multi-court search request."""

    query_type: QueryType
    value: str
    date_range: tuple[date, date] | None = None
    max_results_per_court: int = 20


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Single result returned by one court adapter."""

    court: str
    case_number: str
    cnj_number: str | None
    decision_date: date | None
    relator: str | None
    classe: str | None
    ementa: str
    url: str
    source_query: SearchQuery
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class SearchExplain:
    """Diagnostic metadata produced by the search orchestrator."""

    courts_requested: list[str]
    courts_skipped: list[tuple[str, str]]
    per_court_latency: dict[str, float]
    ranking_weights: dict[str, float]
    dedup_removed: int


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Aggregated response from the unified multi-court search."""

    query: SearchQuery
    results: list[SearchResult]
    courts_queried: list[str]
    courts_failed: list[tuple[str, str]]
    total_count: int
    elapsed_seconds: float
    explain: SearchExplain | None = None
