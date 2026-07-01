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

    def test_vencido_when_lapsed_over_weekend_only(self) -> None:
        # Regression: a deadline lapsing on Friday must read VENCIDO on the following
        # Saturday/Sunday — not URGENTE. dias_uteis_between(Fri, Sat) == 0, so the old
        # `-0 == 0` fell through to URGENTE and showed a blown fatal prazo as "act today".
        cal = JudicialCalendar(uf="mg", include_recesso=False)
        analysis = _analysis(CategoriaSemantica.SENTENCA, data=date(2026, 6, 5))
        rule = shortest_deadline(CategoriaSemantica.SENTENCA)
        assert rule is not None

        prazo = compute_prazo(analysis, rule, cal, today=date(2026, 6, 13), numero_cnj="123")
        assert prazo.data_limite == date(2026, 6, 12)  # a Friday
        assert prazo.status == StatusPrazo.VENCIDO  # lapsed, not URGENTE
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


class TestManualReviewSafetyNet:
    """An actionable movement must never silently vanish or get a fabricated prazo."""

    def _actionable(self, *, data_hora, codigo_tpu=132):
        return AnalysisResult(
            movimento_id="mov-x",
            codigo_tpu=codigo_tpu,
            descricao="Sentença",
            data_hora=data_hora,
            categoria=CategoriaSemantica.SENTENCA,
            urgencia=Urgencia.CRITICA,
            requer_acao=True,
            recomendacao="Test",
            confianca=0.95,
            metodo="rule",
        )

    def test_missing_date_goes_to_manual_review_not_fabricated_prazo(self) -> None:
        # data_hora None (parse failed) must NOT become a phantom deadline (was datetime.min
        # → 0001-01-08 VENCIDO). It goes to manual review instead.
        report = compute_prazos(
            "123", "tjmg", [self._actionable(data_hora=None)], today=date(2026, 6, 15)
        )
        assert report.prazos == []  # no fabricated deadline
        assert len(report.revisao_manual) == 1
        assert report.revisao_manual[0].motivo == "data_ausente"
        assert report.revisao_manual[0].movimento_id == "mov-x"

    def test_actionable_movement_without_rule_goes_to_manual_review(self, monkeypatch) -> None:
        # actionable movement that matches zero prazo rules must be surfaced, never dropped
        monkeypatch.setattr("juris.prazo.engine.find_applicable_rules", lambda *a, **k: [])
        dh = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        report = compute_prazos(
            "123", "tjmg", [self._actionable(data_hora=dh)], today=date(2026, 6, 15)
        )
        assert report.prazos == []
        assert len(report.revisao_manual) == 1
        assert report.revisao_manual[0].motivo == "sem_regra_de_prazo"
