"""Cross-court ranking heuristics for unified search results.

Weights: court_hierarchy=0.4, recency=0.35, term_overlap=0.25.
Fully deterministic — no ML, fully debuggable.
"""

from __future__ import annotations

from datetime import date

from juris.search.models import SearchQuery, SearchResult

# Court hierarchy scores (higher = more authoritative)
_COURT_HIERARCHY: dict[str, float] = {
    "stf": 1.0,
    "stj": 0.9,
    "tst": 0.85,
    "tse": 0.85,
    "stm": 0.80,
}

# Weights for final score
_W_HIERARCHY = 0.40
_W_RECENCY = 0.35
_W_OVERLAP = 0.25

# Reference date for recency — 10 years back scores 0.0
_RECENCY_SPAN_DAYS = 365 * 10


def _court_score(court: str) -> float:
    """Return hierarchy score for a court code."""
    if court in _COURT_HIERARCHY:
        return _COURT_HIERARCHY[court]
    if court.startswith("trf"):
        return 0.70
    if court.startswith("trt"):
        return 0.65
    if court.startswith("tj"):
        return 0.50
    return 0.40


def _recency_score(decision_date: date | None) -> float:
    """Return recency score (0.0–1.0). None dates get 0.0."""
    if decision_date is None:
        return 0.0
    today = date.today()
    delta = (today - decision_date).days
    if delta <= 0:
        return 1.0
    return max(0.0, 1.0 - delta / _RECENCY_SPAN_DAYS)


def _term_overlap_score(ementa: str, query_value: str) -> float:
    """Return term overlap score (0.0–1.0)."""
    query_terms = set(query_value.lower().split())
    if not query_terms:
        return 0.0
    ementa_lower = ementa.lower()
    matched = sum(1 for t in query_terms if t in ementa_lower)
    return matched / len(query_terms)


def compute_score(result: SearchResult, query: SearchQuery) -> float:
    """Compute composite ranking score for a single result."""
    h = _court_score(result.court)
    r = _recency_score(result.decision_date)
    t = _term_overlap_score(result.ementa, query.value)
    return _W_HIERARCHY * h + _W_RECENCY * r + _W_OVERLAP * t


def rank_results(
    results: list[SearchResult],
    query: SearchQuery,
) -> list[SearchResult]:
    """Sort results by composite score (descending).

    Ties broken by court hierarchy, then by decision_date (most recent first).
    """
    if not results:
        return []

    scored = [(compute_score(r, query), r) for r in results]
    scored.sort(
        key=lambda pair: (
            pair[0],
            _court_score(pair[1].court),
            pair[1].decision_date or date.min,
        ),
        reverse=True,
    )
    return [r for _, r in scored]
