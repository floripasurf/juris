"""Tests for defesas.prescricao — prescription verification."""

from __future__ import annotations

from datetime import date

from juris.defesas.models import TipoDefesa
from juris.defesas.prescricao import verificar_prescricao


class TestVerificarPrescricao:
    def test_within_period_indenizatoria(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2022, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
        )
        assert result.tipo == TipoDefesa.PRESCRICAO
        assert result.aplicavel is False
        assert "NAO configurada" in result.fundamentacao

    def test_expired_indenizatoria(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2018, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
        )
        assert result.aplicavel is True
        assert "PRESCRICAO CONFIGURADA" in result.fundamentacao
        assert result.confianca >= 0.9

    def test_expired_cobranca(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Cobranca",
            data_fato=date(2015, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
        )
        assert result.aplicavel is True

    def test_within_period_cobranca(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Cobranca",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
        )
        assert result.aplicavel is False

    def test_unknown_tipo_acao(self) -> None:
        result = verificar_prescricao(
            tipo_acao="XyzNonexistent",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
        )
        assert result.aplicavel is False
        assert result.confianca == 0.3
        assert "nao encontrado" in result.fundamentacao

    def test_with_suspension(self) -> None:
        # 3-year prescription, but 1 year suspended -> effectively 2 years elapsed
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2023, 6, 1),
            causas_suspensao=[(date(2021, 1, 1), date(2022, 1, 1))],
        )
        # 3.4 years elapsed, minus 1 year suspended = 2.4 years effective < 3 years
        assert result.aplicavel is False

    def test_suspension_extends_deadline(self) -> None:
        # Would be expired without suspension, but suspension saves it
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
            causas_suspensao=[(date(2021, 6, 1), date(2023, 6, 1))],
        )
        # 4 years elapsed, minus 2 years suspended = 2 years effective < 3 years
        assert result.aplicavel is False
        assert "suspensao" in result.fundamentacao.lower()

    def test_with_interruption(self) -> None:
        # Interruption restarts the clock
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2018, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
            causas_interrupcao=[date(2022, 1, 1)],
        )
        # Clock restarted at 2022-01-01, 2 years elapsed < 3 years
        assert result.aplicavel is False
        assert "interrupcao" in result.fundamentacao.lower()

    def test_interruption_expired(self) -> None:
        # Even with interruption, still expired
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2015, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
            causas_interrupcao=[date(2018, 1, 1)],
        )
        # Clock restarted at 2018-01-01, 6 years elapsed > 3 years
        assert result.aplicavel is True

    def test_multiple_interruptions_uses_last(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2015, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
            causas_interrupcao=[date(2018, 1, 1), date(2022, 6, 1)],
        )
        # Clock restarted at 2022-06-01 (latest), ~1.5 years < 3 years
        assert result.aplicavel is False

    def test_edge_case_same_day(self) -> None:
        # Filing on the exact same day as the event
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2024, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
        )
        assert result.aplicavel is False

    def test_prazo_geral_10_anos(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Prazo geral",
            data_fato=date(2010, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
        )
        assert result.aplicavel is True

    def test_prazo_geral_within(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Prazo geral",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
        )
        assert result.aplicavel is False

    def test_alimentos_2_anos(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Alimentos",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2023, 6, 1),
        )
        assert result.aplicavel is True

    def test_base_legal_present(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2022, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
        )
        assert result.base_legal != ""
        assert "206" in result.base_legal

    def test_recomendacao_present(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2018, 1, 1),
            data_ajuizamento=date(2024, 1, 1),
        )
        assert result.recomendacao != ""
        assert "prescricao" in result.recomendacao.lower()

    def test_suspension_outside_period_ignored(self) -> None:
        # Suspension before the effective start date
        result = verificar_prescricao(
            tipo_acao="Indenizatoria",
            data_fato=date(2022, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
            causas_suspensao=[(date(2019, 1, 1), date(2020, 1, 1))],
        )
        # Suspension is before data_fato, should be effectively ignored
        assert result.aplicavel is False

    def test_trabalhista_bienal(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Trabalhista bienal",
            data_fato=date(2020, 1, 1),
            data_ajuizamento=date(2023, 6, 1),
        )
        assert result.aplicavel is True

    def test_seguro_1_ano(self) -> None:
        result = verificar_prescricao(
            tipo_acao="Seguro",
            data_fato=date(2023, 1, 1),
            data_ajuizamento=date(2024, 6, 1),
        )
        assert result.aplicavel is True
