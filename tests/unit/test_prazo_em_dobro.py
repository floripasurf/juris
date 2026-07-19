"""Tests for prazo em dobro — arts. 180/183/186 CPC (Fazenda/MP/Defensoria).

Prazo em dobro is applied per-rule and per-call, never as a blind global
multiplier: rules with their own "prazo próprio" (e.g. art. 523 cumprimento,
prazo judicial genérico) and all CLT rules are excluded via
``PrazoRule.admite_dobro``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from juris.agents.analyzer import AnalysisResult
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.prazo.calendar import JudicialCalendar
from juris.prazo.engine import Prazo, compute_prazos

CNJ = "123"
TODAY = date(2026, 4, 15)


def _cal() -> JudicialCalendar:
    return JudicialCalendar(uf="mg", include_recesso=False)


def _movement(
    categoria: CategoriaSemantica,
    codigo_tpu: int | None,
    descricao: str,
    data: date,
    *,
    requer_acao: bool = True,
) -> AnalysisResult:
    return AnalysisResult(
        movimento_id="mov",
        codigo_tpu=codigo_tpu,
        descricao=descricao,
        data_hora=datetime(data.year, data.month, data.day, 12, 0, tzinfo=UTC),
        categoria=categoria,
        urgencia=Urgencia.CRITICA,
        requer_acao=requer_acao,
        recomendacao="Test",
        confianca=0.95,
        metodo="rule",
    )


def _sentenca(data: date = date(2026, 4, 1)) -> AnalysisResult:
    return _movement(CategoriaSemantica.SENTENCA, 132, "Sentença publicada", data)


def _by_nome(prazos: list[Prazo], nome_substr: str) -> Prazo:
    matches = [p for p in prazos if nome_substr in p.rule.nome]
    assert len(matches) == 1, f"esperava 1 prazo contendo {nome_substr!r}, achou {len(matches)}"
    return matches[0]


class TestPrazoEmDobro:
    def test_apelacao_dobra_para_fazenda(self) -> None:
        report = compute_prazos(CNJ, "tjmg", [_sentenca()], _cal(), TODAY, parte_representada="fazenda")
        ap = _by_nome(report.prazos, "Apelação")
        assert ap.dias_uteis_total == 30
        assert "art. 183" in ap.rule.base_legal.lower()

    def test_prazo_judicial_generico_nao_dobra(self) -> None:
        # Prazo próprio (fixado pelo juiz) é exceção expressa dos §§2º/4º.
        mov = _movement(CategoriaSemantica.PRAZO_ABERTO, None, "Prazo judicial fixado", date(2026, 4, 1))
        report = compute_prazos(CNJ, "tjmg", [mov], _cal(), TODAY, parte_representada="fazenda")
        generico = _by_nome(report.prazos, "Prazo judicial genérico")
        assert generico.dias_uteis_total == 5

    def test_cumprimento_nao_dobra(self) -> None:
        # Art. 523 CPC fora — regime da Fazenda é outro (arts. 534-535).
        mov = _movement(CategoriaSemantica.CUMPRIMENTO, 480, "Cumprimento de sentença", date(2026, 4, 1))
        report = compute_prazos(CNJ, "tjmg", [mov], _cal(), TODAY, parte_representada="fazenda")
        pagamento = _by_nome(report.prazos, "Pagamento voluntário")
        assert pagamento.dias_uteis_total == 15

    def test_clt_nao_dobra(self) -> None:
        mov = _movement(CategoriaSemantica.SENTENCA, None, "Sentença trabalhista publicada", date(2026, 4, 1))
        report = compute_prazos(
            CNJ, "trt3", [mov], _cal(), TODAY, justica="trabalho", parte_representada="fazenda"
        )
        ro = _by_nome(report.prazos, "Recurso ordinário")
        assert ro.dias_uteis_total == 8

    def test_reabertura_pos_ed_dobra(self) -> None:
        analyses = [
            _movement(CategoriaSemantica.SENTENCA, 132, "Sentença publicada", date(2026, 1, 5)),
            _movement(CategoriaSemantica.RECURSO, 199, "Embargos de declaração opostos", date(2026, 1, 9)),
            _movement(
                CategoriaSemantica.RECURSO,
                464,
                "Embargos de declaração não providos",
                date(2026, 2, 10),
            ),
        ]
        report = compute_prazos(CNJ, "tjmg", analyses, _cal(), date(2026, 2, 11), parte_representada="fazenda")
        reaberta = _by_nome(report.prazos, "reaberta após embargos")
        assert reaberta.dias_uteis_total == 30

    def test_parte_invalida_levanta(self) -> None:
        with pytest.raises(ValueError, match="parte_representada"):
            compute_prazos(CNJ, "tjmg", [_sentenca()], _cal(), TODAY, parte_representada="banco")

    def test_default_nao_dobra(self) -> None:
        # Comportamento atual (sem parte_representada) permanece inalterado.
        report = compute_prazos(CNJ, "tjmg", [_sentenca()], _cal(), TODAY)
        ap = _by_nome(report.prazos, "Apelação")
        assert ap.dias_uteis_total == 15
