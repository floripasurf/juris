"""Mini-benchmark for minuta quality (Sprint 6)."""

from __future__ import annotations

from juris.agents.citation_verifier import MarkerCitationVerifier
from juris.benchmark.minutas import MinutaCase, run_minuta_benchmark


def test_minuta_benchmark_scores_tone_and_grounding() -> None:
    # allowed_source_ids is supplied, so the verifier never touches the corpus.
    verifier = MarkerCitationVerifier(repertory=object())

    cases = [
        MinutaCase("forte_grounded", "alta", False, "Conforme [CITE:resp_123].", frozenset({"resp_123"}), "forte"),
        MinutaCase("baixa_rascunho", "baixa", False, "Há elementos em [CITE:re_9].", frozenset({"re_9"}), "rascunho"),
        MinutaCase("ungrounded", "alta", False, "Conforme [CITE:inexistente].", frozenset({"resp_123"}), "forte"),
    ]
    report = run_minuta_benchmark(cases, verifier)

    assert report["total"] == 3
    by_name = {s.name: s for s in report["scores"]}
    assert by_name["forte_grounded"].passed is True
    assert by_name["baixa_rascunho"].passed is True
    assert by_name["baixa_rascunho"].not_overassertive is True
    assert by_name["ungrounded"].grounded is False
    assert by_name["ungrounded"].passed is False
    assert "ungrounded" in report["failures"]
