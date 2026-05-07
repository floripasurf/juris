"""Tests for defesas.decadencia — decadence verification."""

from __future__ import annotations

from datetime import date

from juris.defesas.decadencia import verificar_decadencia
from juris.defesas.models import TipoDefesa


class TestVerificarDecadencia:
    def test_cdc_vicio_duravel_within(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio duravel",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 2, 15),
        )
        assert result.tipo == TipoDefesa.DECADENCIA
        assert result.aplicavel is False
        assert "NAO configurada" in result.fundamentacao

    def test_cdc_vicio_duravel_expired(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio duravel",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 7, 1),
        )
        assert result.aplicavel is True
        assert "DECADENCIA CONFIGURADA" in result.fundamentacao

    def test_cdc_vicio_nao_duravel_30_dias(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio nao duravel",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 3, 1),
        )
        assert result.aplicavel is True

    def test_cdc_vicio_nao_duravel_within(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio nao duravel",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 1, 20),
        )
        assert result.aplicavel is False

    def test_anulatoria_4_anos(self) -> None:
        result = verificar_decadencia(
            tipo_direito="anulatoria",
            data_ciencia=date(2018, 1, 1),
            data_exercicio=date(2024, 1, 1),
        )
        assert result.aplicavel is True

    def test_anulatoria_within(self) -> None:
        result = verificar_decadencia(
            tipo_direito="anulatoria",
            data_ciencia=date(2022, 1, 1),
            data_exercicio=date(2024, 1, 1),
        )
        assert result.aplicavel is False

    def test_unknown_tipo(self) -> None:
        result = verificar_decadencia(
            tipo_direito="xyznonexistent",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 6, 1),
        )
        assert result.aplicavel is False
        assert result.confianca == 0.3

    def test_defaults_to_today(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio duravel",
            data_ciencia=date(2020, 1, 1),
        )
        # Should use today as data_exercicio — expired long ago
        assert result.aplicavel is True

    def test_no_suspension_mention(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio duravel",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 7, 1),
        )
        assert "207" in result.fundamentacao  # Art. 207 CC - no suspension

    def test_base_legal_present(self) -> None:
        result = verificar_decadencia(
            tipo_direito="cdc vicio duravel",
            data_ciencia=date(2024, 1, 1),
            data_exercicio=date(2024, 2, 1),
        )
        assert "26" in result.base_legal
