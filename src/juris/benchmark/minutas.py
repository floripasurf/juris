"""Mini-benchmark for minuta quality (Sprint 6) — deterministic, no LLM needed.

Scores each scenario on the invariants that must hold regardless of the model:

* **tone** — ``tom_minuta`` maps the strategy's confidence/review to the expected
  firmness (forte / cauteloso / rascunho / não protocolar);
* **not over-assertive** — a low-confidence or review-mandatory line NEVER drafts
  "forte" (the Sprint 6 done-when);
* **grounded** — every ``[CITE:id]`` resolves to an allowed source and no spurious
  prose citation slips through (reuses the real anti-hallucination verifier).

It is meant to grow: append real pilot minutas as scenarios and track the pass rate
across corpus/prompt changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from juris.agents.estrategia import tom_minuta


@dataclass(frozen=True, slots=True)
class MinutaCase:
    """One benchmark scenario: strategy inputs + the draft it should have produced."""

    name: str
    confianca: str
    revisao_obrigatoria: bool
    draft: str
    allowed_source_ids: frozenset[str]
    expected_tone: str


@dataclass(frozen=True, slots=True)
class MinutaScore:
    name: str
    tone: str
    tone_ok: bool
    not_overassertive: bool
    grounded: bool

    @property
    def passed(self) -> bool:
        return self.tone_ok and self.not_overassertive and self.grounded


class _Verifier:
    """Minimal structural type for the injected citation verifier."""

    def verify(self, draft: str, allowed_source_ids: set[str] | None = None) -> object: ...


def score_minuta(case: MinutaCase, verifier: _Verifier) -> MinutaScore:
    """Score one scenario. ``verifier`` is a MarkerCitationVerifier (injected so the
    benchmark stays LLM- and corpus-free when ``allowed_source_ids`` is supplied)."""
    tone = tom_minuta(case.confianca, revisao_obrigatoria=case.revisao_obrigatoria)
    tone_ok = tone == case.expected_tone
    low = case.confianca == "baixa" or case.revisao_obrigatoria
    not_overassertive = not (low and tone == "forte")

    result = verifier.verify(case.draft, allowed_source_ids=set(case.allowed_source_ids))
    grounded = bool(getattr(result, "all_passed", False)) and not getattr(result, "spurious_citations", [])

    return MinutaScore(
        name=case.name,
        tone=tone,
        tone_ok=tone_ok,
        not_overassertive=not_overassertive,
        grounded=grounded,
    )


def run_minuta_benchmark(cases: list[MinutaCase], verifier: _Verifier) -> dict[str, object]:
    """Run all scenarios and return a summary + per-scenario scores."""
    scores = [score_minuta(c, verifier) for c in cases]
    passed = sum(1 for s in scores if s.passed)
    return {
        "total": len(scores),
        "passed": passed,
        "pass_rate": round(passed / len(scores), 4) if scores else 0.0,
        "failures": [s.name for s in scores if not s.passed],
        "scores": scores,
    }
