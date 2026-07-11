"""Citation lookup utilities: normalization, tenant scope and fail-safe errors."""

from __future__ import annotations

from typing import Any

from juris.repertory.citation_lookup import normalize_citation, resolve_narrative_citation, resolve_source_id
from juris.repertory.retrieval.service import RetrievalResult


def _result(source_id: str, *, score: float = 0.9, texto: str = "texto do precedente") -> RetrievalResult:
    return RetrievalResult(
        source_id=source_id,
        score=score,
        hierarchy=4,
        hierarchy_label="Súmula",
        tribunal="STJ",
        texto=texto,
        tipo="sumula",
        uso="fundamento",
    )


class _FakeRepertory:
    def __init__(self, results: list[RetrievalResult] | None = None, *, fail: bool = False) -> None:
        self.results = results or []
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def search_jurisprudencia(self, **kwargs: Any) -> list[RetrievalResult]:
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("repertory offline")
        return list(self.results)


def test_normalize_citation_standardizes_spacing_case_and_abbreviations() -> None:
    assert normalize_citation("  Súmula   n. 297  do STJ ") == "súmula numero 297 do stj"
    assert normalize_citation("Arts.  489 e 1.022") == "artigos 489 e 1.022"


def test_resolve_source_id_scopes_lookup_to_tenant_and_returns_excerpt() -> None:
    repertory = _FakeRepertory([_result("src-1", texto="x" * 250), _result("src-2")])

    found, excerpt = resolve_source_id("src-1", repertory, tenant_id="escritorio-a")  # type: ignore[arg-type]

    assert found is True
    assert excerpt == "x" * 200
    assert repertory.calls[0]["query"] == "src-1"
    assert repertory.calls[0]["tenant_id"] == "escritorio-a"


def test_resolve_source_id_returns_false_when_only_other_sources_match() -> None:
    repertory = _FakeRepertory([_result("src-other")])

    assert resolve_source_id("src-1", repertory) == (False, None)  # type: ignore[arg-type]


def test_resolve_narrative_citation_applies_threshold_and_tenant_scope() -> None:
    repertory = _FakeRepertory([_result("sumula-297-stj", score=0.42)])

    found, source_id = resolve_narrative_citation(
        "Súmula n. 297 do STJ", repertory, threshold=0.4, tenant_id="escritorio-a"  # type: ignore[arg-type]
    )

    assert (found, source_id) == (True, "sumula-297-stj")
    assert repertory.calls[0]["query"] == "súmula numero 297 do stj"
    assert repertory.calls[0]["tenant_id"] == "escritorio-a"


def test_lookup_failures_are_not_treated_as_verified() -> None:
    repertory = _FakeRepertory(fail=True)

    assert resolve_source_id("src-1", repertory) == (False, None)  # type: ignore[arg-type]
    assert resolve_narrative_citation("Súmula 1", repertory) == (False, None)  # type: ignore[arg-type]
