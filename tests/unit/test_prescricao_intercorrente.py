"""Tests for defesas.prescricao_intercorrente."""

from __future__ import annotations

from datetime import date, timedelta

from juris.defesas.models import TipoDefesa
from juris.defesas.prescricao_intercorrente import verificar_prescricao_intercorrente


class TestVerificarPrescricaoIntercorrente:
    def test_not_expired_recent_suspension(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date.today() - timedelta(days=100),
            data_suspensao=date.today() - timedelta(days=90),
            prazo_original_anos=3,
        )
        assert result.tipo == TipoDefesa.PRESCRICAO_INTERCORRENTE
        assert result.aplicavel is False

    def test_expired_old_suspension(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2015, 1, 1),
            data_suspensao=date(2015, 1, 1),
            prazo_original_anos=3,
        )
        # 1 year suspension + 3 years prescription = 4 years total from 2015
        # By now (2026), well past the limit
        assert result.aplicavel is True
        assert "PRESCRICAO INTERCORRENTE CONFIGURADA" in result.fundamentacao

    def test_uses_suspension_date(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2015, 1, 1),
            data_suspensao=date(2016, 1, 1),
            prazo_original_anos=3,
        )
        assert result.aplicavel is True
        assert "2016" in result.fundamentacao

    def test_uses_ultimo_ato_when_no_suspension(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2015, 1, 1),
            data_suspensao=None,
            prazo_original_anos=3,
        )
        assert result.aplicavel is True

    def test_invalid_prazo(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2020, 1, 1),
            data_suspensao=None,
            prazo_original_anos=0,
        )
        assert result.aplicavel is False
        assert result.confianca == 0.3

    def test_negative_prazo(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2020, 1, 1),
            data_suspensao=None,
            prazo_original_anos=-1,
        )
        assert result.aplicavel is False

    def test_base_legal(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2020, 1, 1),
            data_suspensao=None,
            prazo_original_anos=3,
        )
        assert "921" in result.base_legal
        assert "150" in result.base_legal

    def test_recomendacao_when_expired(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2015, 1, 1),
            data_suspensao=None,
            prazo_original_anos=3,
        )
        assert "requerer" in result.recomendacao.lower() or "reconhecimento" in result.recomendacao.lower()

    def test_5_year_prazo(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date(2018, 1, 1),
            data_suspensao=date(2018, 1, 1),
            prazo_original_anos=5,
        )
        # 1yr suspension + 5yr = 6yr from 2018 = 2024
        # Today is 2026, so expired
        assert result.aplicavel is True

    def test_confianca_range(self) -> None:
        result = verificar_prescricao_intercorrente(
            data_ultimo_ato=date.today() - timedelta(days=30),
            data_suspensao=None,
            prazo_original_anos=3,
        )
        assert 0.0 <= result.confianca <= 1.0
