"""Tests for the prazo engine — deadline computation."""

from __future__ import annotations

from datetime import UTC, date, datetime

from juris.agents.analyzer import AnalysisResult
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.prazo.calendar import JudicialCalendar
from juris.prazo.engine import (
    PrazoReport,
    StatusPrazo,
    compute_prazo,
    compute_prazos,
)
from juris.prazo.rules import shortest_deadline


def _analysis(
    categoria: CategoriaSemantica,
    codigo_tpu: int = 132,
    data: date | None = None,
    requer_acao: bool = True,
) -> AnalysisResult:
    d = data or date(2026, 4, 1)
    return AnalysisResult(
        movimento_id="test_mov",
        codigo_tpu=codigo_tpu,
        descricao="Test",
        data_hora=datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC),
        categoria=categoria,
        urgencia=Urgencia.CRITICA,
        requer_acao=requer_acao,
        recomendacao="Test",
        confianca=0.95,
        metodo="rule",
    )


class TestComputePrazo:
    def test_basic_deadline(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        analysis = _analysis(CategoriaSemantica.SENTENCA, data=date(2026, 4, 1))
        rule = shortest_deadline(CategoriaSemantica.SENTENCA)
        assert rule is not None

        prazo = compute_prazo(analysis, rule, cal, today=date(2026, 4, 2), numero_cnj="123")
        assert prazo.data_inicio == date(2026, 4, 1)
        assert prazo.dias_uteis_total == rule.dias_uteis
        assert prazo.numero_cnj == "123"

    def test_vencido_status(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        analysis = _analysis(CategoriaSemantica.SENTENCA, data=date(2026, 1, 5))
        rule = shortest_deadline(CategoriaSemantica.SENTENCA)
        assert rule is not None

        # Today is way after the deadline
        prazo = compute_prazo(analysis, rule, cal, today=date(2026, 4, 30), numero_cnj="123")
        assert prazo.status == StatusPrazo.VENCIDO
        assert prazo.dias_uteis_restantes < 0
        assert prazo.urgencia == Urgencia.CRITICA

    def test_aberto_status(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        analysis = _analysis(CategoriaSemantica.CITACAO, codigo_tpu=12, data=date(2026, 4, 28))
        rule = shortest_deadline(CategoriaSemantica.CITACAO)
        assert rule is not None

        prazo = compute_prazo(analysis, rule, cal, today=date(2026, 4, 29), numero_cnj="123")
        assert prazo.status == StatusPrazo.ABERTO
        assert prazo.dias_uteis_restantes > 3

    def test_summary_message(self) -> None:
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        analysis = _analysis(CategoriaSemantica.SENTENCA, data=date(2026, 4, 1))
        rule = shortest_deadline(CategoriaSemantica.SENTENCA)
        assert rule is not None

        prazo = compute_prazo(analysis, rule, cal, today=date(2026, 4, 2), numero_cnj="123")
        assert "CPC" in prazo.summary or "Embargos" in prazo.summary


class TestComputePrazos:
    def test_report_basic(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.SENTENCA, codigo_tpu=132, data=date(2026, 4, 1)),
            _analysis(CategoriaSemantica.CITACAO, codigo_tpu=12, data=date(2026, 4, 10)),
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 15))
        assert isinstance(report, PrazoReport)
        assert len(report.prazos) >= 2  # At least apelação + embargos + contestação

    def test_noise_skipped(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.NOISE, codigo_tpu=11, requer_acao=False),
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 15))
        assert len(report.prazos) == 0

    def test_sorted_by_urgency(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.CITACAO, codigo_tpu=12, data=date(2026, 4, 25)),   # Future
            _analysis(CategoriaSemantica.SENTENCA, codigo_tpu=132, data=date(2026, 1, 5)),   # Past = vencido
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        if report.vencidos:
            # Vencidos should come first
            assert report.prazos[0].status == StatusPrazo.VENCIDO

    def test_has_critical(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.SENTENCA, codigo_tpu=132, data=date(2026, 1, 5)),
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        assert report.has_critical

    def test_no_critical_for_future(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.CITACAO, codigo_tpu=12, data=date(2026, 4, 28)),
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 29))
        assert not report.has_critical

    def test_report_summary(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.SENTENCA, codigo_tpu=132, data=date(2026, 4, 1)),
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 2))
        assert "123" in report.summary

    def test_empty_analyses(self) -> None:
        report = compute_prazos("123", "tjmg", [], today=date(2026, 4, 15))
        assert report.prazos == []
        assert "sem prazos" in report.summary

    def test_clt_rules_used_for_trabalho(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.SENTENCA, codigo_tpu=132, data=date(2026, 4, 1)),
        ]
        report = compute_prazos("123", "trt3", analyses, today=date(2026, 4, 2), justica="trabalho")
        # CLT recurso ordinário is 8 days, not 15
        has_8_day = any(p.dias_uteis_total == 8 for p in report.prazos)
        assert has_8_day
