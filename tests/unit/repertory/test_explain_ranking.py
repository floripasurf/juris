"""Tests for exposing the composite ranking signals (fonte/vigência/autoridade/…)."""

from __future__ import annotations

from juris.repertory.retrieval.service import RetrievalResult, explain_ranking


def _result(components):
    return RetrievalResult(
        source_id="src-1", score=0.8, hierarchy=2, hierarchy_label="STJ precedente",
        tribunal="STJ", texto="…", score_components=components,
    )


def test_explain_surfaces_all_signals_and_dominant_motivo() -> None:
    comps = {"relevancia": 0.3, "autoridade": 0.9, "vigencia": 1.0, "corroboracao": 0.4, "total": 0.75}
    ex = explain_ranking(_result(comps))
    assert "STJ" in ex["fonte"]
    assert ex["autoridade"] == 0.9
    assert ex["vigencia"] == 1.0
    assert ex["corroboracao"] == 0.4
    assert ex["score_total"] == 0.75
    assert "vigente" in ex["motivo"].lower()  # vigencia is the strongest driver


def test_explain_without_components_flags_relevance_only() -> None:
    ex = explain_ranking(_result(None))
    assert ex["motivo"]  # non-empty
    assert ex["score_total"] == 0.8  # falls back to score
