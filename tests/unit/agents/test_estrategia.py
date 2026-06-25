"""Tests for the argumentative-line selector (ADR-0017 filter, Stage 2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from juris.agents.estrategia import (
    EstrategiaAgent,
    LinhaArgumentativa,
    score_linha,
    selecionar_linha,
    verificar_deontologia,
)


def _prec(source_id: str, hierarchy: int) -> SimpleNamespace:
    return SimpleNamespace(source_id=source_id, hierarchy=hierarchy)


class TestScoreLinha:
    def test_grounded_citations_beat_hallucinated(self) -> None:
        precs = [_prec("A", 1), _prec("B", 3)]
        grounded = LinhaArgumentativa(tese="x", citacoes=["A", "B"])
        hallucinated = LinhaArgumentativa(tese="y", citacoes=["Z"])  # Z is not real
        assert score_linha(grounded, precs) > score_linha(hallucinated, precs)

    def test_higher_authority_citations_score_higher(self) -> None:
        precs = [_prec("A", 1), _prec("B", 6)]
        high = LinhaArgumentativa(tese="x", citacoes=["A"])
        low = LinhaArgumentativa(tese="y", citacoes=["B"])
        assert score_linha(high, precs) > score_linha(low, precs)

    def test_risks_penalise(self) -> None:
        precs = [_prec("A", 1)]
        safe = LinhaArgumentativa(tese="x", citacoes=["A"])
        risky = LinhaArgumentativa(tese="x", citacoes=["A"], riscos=["prescrição", "preclusão"])
        assert safe.tese == risky.tese
        assert score_linha(safe, precs) > score_linha(risky, precs)


class TestSelecionarLinha:
    def test_returns_best_and_runners_up(self) -> None:
        precs = [_prec("A", 1)]
        candidatas = [
            LinhaArgumentativa(tese="fraca", citacoes=["Z"]),
            LinhaArgumentativa(tese="forte", citacoes=["A"]),
        ]
        result = selecionar_linha(candidatas, precs)
        assert result.escolhida.tese == "forte"
        assert [a.tese for a in result.alternativas] == ["fraca"]
        assert result.escolhida.score >= result.alternativas[0].score

    def test_assigns_argument_hierarchy_by_rank(self) -> None:
        # Módulo C: principal / subsidiária / eventual.
        precs = [_prec("A", 1)]
        cands = [
            LinhaArgumentativa(tese="t1", citacoes=["A"]),
            LinhaArgumentativa(tese="t2", citacoes=["A"]),
            LinhaArgumentativa(tese="t3", citacoes=["A"]),
        ]
        result = selecionar_linha(cands, precs)
        assert result.escolhida.ordem == "principal"
        assert result.alternativas[0].ordem == "subsidiaria"
        assert result.alternativas[1].ordem == "eventual"

    def test_confianca_calibrated_from_score(self) -> None:
        # Módulo G: firmeza ∝ solidez. Grounded + nível-1 → score alto → alta.
        precs = [_prec("A", 1)]
        forte = selecionar_linha([LinhaArgumentativa(tese="forte", citacoes=["A"])], precs)
        assert forte.escolhida.confianca == "alta"

        # Citação alucinada (Z não existe) → score 0 → baixa.
        fraca = selecionar_linha([LinhaArgumentativa(tese="fraca", citacoes=["Z"])], precs)
        assert fraca.escolhida.confianca == "baixa"

    def test_deontological_veto_flags_and_forces_review(self) -> None:
        # Módulo I: linha que afirma resultado garantido → vedação CED.
        precs = [_prec("A", 1)]
        cands = [LinhaArgumentativa(tese="A procedência é certa, êxito garantido.", citacoes=["A"])]
        result = selecionar_linha(cands, precs)
        assert result.avisos_deontologicos  # flagged, not silently kept
        assert result.revisao_humana_obrigatoria is True

    def test_clean_high_confidence_line_needs_no_mandatory_review(self) -> None:
        precs = [_prec("A", 1)]
        cands = [LinhaArgumentativa(tese="Há fundamento sólido para a tese.", citacoes=["A"])]
        result = selecionar_linha(cands, precs)
        assert result.avisos_deontologicos == []
        assert result.revisao_humana_obrigatoria is False


class TestDeontologia:
    def test_flags_guaranteed_result_language(self) -> None:
        # CED: tom proporcional à solidez; vedado afirmar êxito garantido.
        linha = LinhaArgumentativa(tese="Vitória garantida, sem risco algum.")
        avisos = verificar_deontologia(linha)
        assert avisos
        assert all(isinstance(a, str) for a in avisos)

    def test_flags_inevitability_in_fundamentos(self) -> None:
        linha = LinhaArgumentativa(tese="Tese X", fundamentos=["O desfecho é inevitável."])
        assert verificar_deontologia(linha)

    def test_sober_line_has_no_avisos(self) -> None:
        linha = LinhaArgumentativa(
            tese="Há fundamento para a tese, com risco moderado de improcedência."
        )
        assert verificar_deontologia(linha) == []


@pytest.mark.asyncio
async def test_agent_generates_candidates_then_selects_the_grounded_one() -> None:
    precs = [_prec("A", 1)]
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=SimpleNamespace(
            content='[{"tese": "forte", "fundamentos": ["f"], "citacoes": ["A"]},'
            ' {"tese": "fraca", "fundamentos": [], "citacoes": ["Z"]}]'
        )
    )

    result = await EstrategiaAgent(llm).propor(contexto="Caso de cobrança", precedentes=precs)

    assert result.escolhida.tese == "forte"
    llm.complete.assert_awaited_once()
