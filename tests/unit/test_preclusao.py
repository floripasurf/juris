"""Tests for defesas.preclusao — preclusion verification."""

from __future__ import annotations

from juris.defesas.models import TipoDefesa
from juris.defesas.preclusao import verificar_preclusao


class TestPreclusaoTemporal:
    def test_no_prazo_rule(self) -> None:
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
            movimentos=[],
            prazo_rule=None,
        )
        assert result.aplicavel is False
        assert result.confianca == 0.3

    def test_with_decurso_movement(self) -> None:
        movimentos = [
            {"codigo": 493, "data": "2024-01-15"},  # Anotacao (decurso indicator)
        ]
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
            movimentos=movimentos,
            prazo_rule={"dias": 15},
        )
        assert result.aplicavel is True
        assert "223" in result.base_legal

    def test_no_decurso_movement(self) -> None:
        movimentos = [
            {"codigo": 581, "data": "2024-01-15"},  # Juntada peticao
        ]
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
            movimentos=movimentos,
            prazo_rule={"dias": 15},
        )
        assert result.aplicavel is False


class TestPreclusaoConsumativa:
    def test_no_duplicates(self) -> None:
        movimentos = [
            {"codigo": 584, "data": "2024-01-10"},  # Juntada contestacao
            {"codigo": 581, "data": "2024-01-15"},  # Juntada peticao
        ]
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_CONSUMATIVA,
            movimentos=movimentos,
        )
        assert result.aplicavel is False

    def test_with_duplicate_contestacao(self) -> None:
        movimentos = [
            {"codigo": 584, "data": "2024-01-10"},
            {"codigo": 584, "data": "2024-01-20"},  # Duplicate
        ]
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_CONSUMATIVA,
            movimentos=movimentos,
        )
        assert result.aplicavel is True
        assert "507" in result.base_legal

    def test_empty_movimentos(self) -> None:
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_CONSUMATIVA,
            movimentos=[],
        )
        assert result.aplicavel is False


class TestPreclusaoLogica:
    def test_no_incompatible_acts(self) -> None:
        movimentos = [
            {"codigo": 581, "data": "2024-01-10"},
        ]
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_LOGICA,
            movimentos=movimentos,
        )
        assert result.aplicavel is False

    def test_acceptance_then_appeal(self) -> None:
        movimentos = [
            {"codigo": 1051, "data": "2024-01-10"},  # Homologacao acordo
            {"codigo": 197, "data": "2024-01-20"},   # Apelacao
        ]
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_LOGICA,
            movimentos=movimentos,
        )
        assert result.aplicavel is True
        assert "1.000" in result.base_legal

    def test_empty_movimentos(self) -> None:
        result = verificar_preclusao(
            tipo=TipoDefesa.PRECLUSAO_LOGICA,
            movimentos=[],
        )
        assert result.aplicavel is False


class TestInvalidTipo:
    def test_invalid_tipo(self) -> None:
        result = verificar_preclusao(
            tipo=TipoDefesa.PRESCRICAO,  # Not a preclusao type
            movimentos=[],
        )
        assert result.aplicavel is False
        assert result.confianca == 0.3
