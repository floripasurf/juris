"""Tests for juris.repertory.corpus.models."""

from __future__ import annotations

from datetime import date

import pytest

from juris.repertory.corpus.models import (
    HIERARCHY_WEIGHTS,
    TIPO_HIERARQUIA,
    FonteJurisprudencia,
    TipoFonte,
)


class TestTipoFonte:
    def test_all_tipos_have_hierarchy(self) -> None:
        for tipo in TipoFonte:
            assert tipo in TIPO_HIERARQUIA

    def test_hierarchy_ordering(self) -> None:
        assert TIPO_HIERARQUIA[TipoFonte.SUMULA_VINCULANTE] < TIPO_HIERARQUIA[TipoFonte.RE_STF]
        assert TIPO_HIERARQUIA[TipoFonte.RE_STF] < TIPO_HIERARQUIA[TipoFonte.RESP_REPETITIVO]
        assert TIPO_HIERARQUIA[TipoFonte.RESP_REPETITIVO] < TIPO_HIERARQUIA[TipoFonte.SUMULA]
        assert TIPO_HIERARQUIA[TipoFonte.SUMULA] < TIPO_HIERARQUIA[TipoFonte.JURISPRUDENCIA_UNIFORME]
        assert TIPO_HIERARQUIA[TipoFonte.JURISPRUDENCIA_UNIFORME] < TIPO_HIERARQUIA[TipoFonte.PRECEDENTE_LOCAL]

    def test_string_values(self) -> None:
        assert TipoFonte.SUMULA_VINCULANTE.value == "sumula_vinculante"
        assert TipoFonte.PRECEDENTE_LOCAL.value == "precedente_local"

    def test_tipo_is_string_enum(self) -> None:
        assert isinstance(TipoFonte.SUMULA_VINCULANTE, str)


class TestHierarchyWeights:
    def test_six_levels(self) -> None:
        assert len(HIERARCHY_WEIGHTS) == 6

    def test_higher_hierarchy_has_higher_weight(self) -> None:
        for i in range(1, 6):
            assert HIERARCHY_WEIGHTS[i] > HIERARCHY_WEIGHTS[i + 1]

    def test_sv_weight_is_highest(self) -> None:
        assert HIERARCHY_WEIGHTS[1] == 3.0

    def test_precedente_local_weight_is_lowest(self) -> None:
        assert HIERARCHY_WEIGHTS[6] == 1.0


class TestFonteJurisprudencia:
    def test_create_minimal(self) -> None:
        fonte = FonteJurisprudencia(
            id="sv_1",
            tribunal="STF",
            tipo=TipoFonte.SUMULA_VINCULANTE,
            numero="1",
            ementa="Test ementa",
        )
        assert fonte.id == "sv_1"
        assert fonte.hierarquia == 6  # default

    def test_create_full(self) -> None:
        fonte = FonteJurisprudencia(
            id="sv_1",
            tribunal="STF",
            tipo=TipoFonte.SUMULA_VINCULANTE,
            numero="1",
            ementa="Test ementa",
            texto_integral="Full text",
            relator="Min. Teste",
            data_julgamento=date(2020, 1, 1),
            temas=["direito adquirido"],
            assuntos_cnj=["12345"],
            base_legal=["CF Art. 5"],
            situacao="vigente",
            hierarquia=1,
        )
        assert fonte.relator == "Min. Teste"
        assert fonte.hierarquia == 1

    def test_hierarchy_label(self) -> None:
        fonte = FonteJurisprudencia(
            id="sv_1", tribunal="STF", tipo=TipoFonte.SUMULA_VINCULANTE,
            numero="1", ementa="Test", hierarquia=1,
        )
        assert fonte.hierarchy_label == "Súmula Vinculante"

    def test_frozen_dataclass(self) -> None:
        fonte = FonteJurisprudencia(
            id="sv_1", tribunal="STF", tipo=TipoFonte.SUMULA_VINCULANTE,
            numero="1", ementa="Test",
        )
        with pytest.raises(AttributeError):
            fonte.id = "changed"  # type: ignore[misc]

    def test_invalid_hierarquia_raises(self) -> None:
        with pytest.raises(ValueError, match="hierarquia must be between"):
            FonteJurisprudencia(
                id="sv_1", tribunal="STF", tipo=TipoFonte.SUMULA_VINCULANTE,
                numero="1", ementa="Test", hierarquia=0,
            )

    def test_invalid_hierarquia_too_high(self) -> None:
        with pytest.raises(ValueError, match="hierarquia must be between"):
            FonteJurisprudencia(
                id="sv_1", tribunal="STF", tipo=TipoFonte.SUMULA_VINCULANTE,
                numero="1", ementa="Test", hierarquia=7,
            )
