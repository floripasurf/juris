"""Tests for deadline alert generation."""

from __future__ import annotations

from datetime import UTC, date, datetime

from juris.agents.analyzer import AnalysisResult
from juris.alerts.deadline_alerts import AlertLevel, generate_alerts
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.prazo.engine import compute_prazos


def _analysis(
    categoria: CategoriaSemantica,
    codigo_tpu: int,
    data: date,
) -> AnalysisResult:
    return AnalysisResult(
        movimento_id="test_mov",
        codigo_tpu=codigo_tpu,
        descricao="Test",
        data_hora=datetime(data.year, data.month, data.day, 12, 0, tzinfo=UTC),
        categoria=categoria,
        urgencia=Urgencia.CRITICA,
        requer_acao=True,
        recomendacao="Test",
        confianca=0.95,
        metodo="rule",
    )


class TestGenerateAlerts:
    def test_vencido_generates_critical(self) -> None:
        analyses = [_analysis(CategoriaSemantica.SENTENCA, 132, date(2026, 1, 5))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        alerts = generate_alerts(report)
        assert alerts.has_critical
        assert any(a.level == AlertLevel.CRITICAL for a in alerts.alerts)

    def test_future_no_critical(self) -> None:
        analyses = [_analysis(CategoriaSemantica.CITACAO, 12, date(2026, 4, 28))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 29))
        alerts = generate_alerts(report)
        assert not alerts.has_critical

    def test_include_info_false_filters(self) -> None:
        analyses = [_analysis(CategoriaSemantica.CITACAO, 12, date(2026, 4, 28))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 29))
        alerts_no_info = generate_alerts(report, include_info=False)
        alerts_with_info = generate_alerts(report, include_info=True)
        assert len(alerts_with_info.alerts) >= len(alerts_no_info.alerts)

    def test_alert_has_message(self) -> None:
        analyses = [_analysis(CategoriaSemantica.SENTENCA, 132, date(2026, 1, 5))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        alerts = generate_alerts(report)
        for a in alerts.alerts:
            assert a.message
            assert len(a.message) > 10

    def test_alert_message_vencido_mentions_vencido(self) -> None:
        analyses = [_analysis(CategoriaSemantica.SENTENCA, 132, date(2026, 1, 5))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        alerts = generate_alerts(report)
        critical = [a for a in alerts.alerts if a.level == AlertLevel.CRITICAL]
        assert any("VENCIDO" in a.message or "HOJE" in a.message for a in critical)

    def test_sorted_by_level(self) -> None:
        analyses = [
            _analysis(CategoriaSemantica.CITACAO, 12, date(2026, 4, 25)),   # Future = info
            _analysis(CategoriaSemantica.SENTENCA, 132, date(2026, 1, 5)),  # Vencido = critical
        ]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        alerts = generate_alerts(report, include_info=True)
        if len(alerts.alerts) >= 2:
            levels = [a.level for a in alerts.alerts]
            # Critical should come before non-critical
            first_non_critical = next((i for i, l in enumerate(levels) if l != AlertLevel.CRITICAL), len(levels))
            assert all(l == AlertLevel.CRITICAL for l in levels[:first_non_critical])

    def test_empty_report(self) -> None:
        report = compute_prazos("123", "tjmg", [], today=date(2026, 4, 30))
        alerts = generate_alerts(report)
        assert alerts.alerts == []
        assert "sem alertas" in alerts.summary

    def test_summary(self) -> None:
        analyses = [_analysis(CategoriaSemantica.SENTENCA, 132, date(2026, 1, 5))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        alerts = generate_alerts(report)
        assert "123" in alerts.summary
        assert "critico" in alerts.summary

    def test_short_message(self) -> None:
        analyses = [_analysis(CategoriaSemantica.SENTENCA, 132, date(2026, 1, 5))]
        report = compute_prazos("123", "tjmg", analyses, today=date(2026, 4, 30))
        alerts = generate_alerts(report)
        for a in alerts.alerts:
            assert a.short_message
            assert "CRITICAL" in a.short_message or "WARNING" in a.short_message or "INFO" in a.short_message
