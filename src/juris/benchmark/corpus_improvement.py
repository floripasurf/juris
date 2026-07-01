"""Measure the corpus moat (Sprint 5): does a second run improve after a gap is filled?

The Sprint 5 done-when — "segunda execução melhora resultado em casos do piloto" — is a
*measurement*, not a one-off. This harness makes it repeatable and deterministic:

1. run a set of retrieval cases against the corpus and score grounding
   (did an expected inteiro-teor source surface in the top-k?);
2. ingest the sources the pilot flagged as missing;
3. re-run and compare.

Feed it the real pilot cases + the real sources and the same numbers prove (or refute)
that the moat is paying off. It is LLM-free and deterministic so it runs in CI and gates
corpus changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    """One case: a query and the inteiro-teor source(s) it should ground on."""

    name: str
    query: str
    expected_source_ids: frozenset[str]


class _Searcher(Protocol):
    def search_jurisprudencia(  # noqa: D102
        self, query: str, top_k: int = 10, tenant_id: str | None = None
    ) -> list[Any]: ...


def measure_grounding(
    cases: list[RetrievalCase], service: _Searcher, *, top_k: int = 5, tenant_id: str | None = None
) -> dict[str, object]:
    """Score how many cases ground on an expected source in the top-k."""
    per_case: list[dict[str, object]] = []
    grounded = 0
    for case in cases:
        results = service.search_jurisprudencia(case.query, top_k=top_k, tenant_id=tenant_id)
        found = {getattr(r, "source_id", None) for r in results}
        ok = bool(case.expected_source_ids & found)
        grounded += ok
        per_case.append({"name": case.name, "grounded": ok})
    total = len(cases)
    return {
        "total": total,
        "grounded": grounded,
        "grounding_rate": round(grounded / total, 4) if total else 0.0,
        "per_case": per_case,
    }


def compare_runs(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    """Compare two :func:`measure_grounding` runs — did the corpus change help?"""
    before_rate = float(cast("float", before["grounding_rate"]))
    after_rate = float(cast("float", after["grounding_rate"]))
    before_cases = cast("list[dict[str, Any]]", before["per_case"])
    after_cases = cast("list[dict[str, Any]]", after["per_case"])
    return {
        "before_grounding_rate": before_rate,
        "after_grounding_rate": after_rate,
        "delta": round(after_rate - before_rate, 4),
        "improved": after_rate > before_rate,
        "newly_grounded": [
            b["name"]
            for b, a in zip(before_cases, after_cases, strict=False)
            if not b["grounded"] and a["grounded"]
        ],
    }
