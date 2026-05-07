"""Tests for defesas.cc_prazos — prescription periods data and lookup."""

from __future__ import annotations

from juris.defesas.cc_prazos import PRAZOS_PRESCRICAO, buscar_prazo_prescricional


class TestPrazosPrescricao:
    def test_has_entries(self) -> None:
        assert len(PRAZOS_PRESCRICAO) >= 18

    def test_all_have_required_fields(self) -> None:
        for p in PRAZOS_PRESCRICAO:
            assert p.tipo_acao
            assert p.prazo_anos > 0 or p.prazo_anos == 0
            assert p.base_legal
            assert p.termo_inicial
            assert isinstance(p.notas, str)

    def test_prazo_geral_is_10_anos(self) -> None:
        geral = buscar_prazo_prescricional("Prazo geral")
        assert geral is not None
        assert geral.prazo_anos == 10
        assert "205" in geral.base_legal

    def test_indenizatoria_is_3_anos(self) -> None:
        p = buscar_prazo_prescricional("Indenizatoria")
        assert p is not None
        assert p.prazo_anos == 3

    def test_cobranca_is_5_anos(self) -> None:
        p = buscar_prazo_prescricional("Cobranca")
        assert p is not None
        assert p.prazo_anos == 5

    def test_alimentos_is_2_anos(self) -> None:
        p = buscar_prazo_prescricional("Alimentos")
        assert p is not None
        assert p.prazo_anos == 2

    def test_seguro_is_1_ano(self) -> None:
        p = buscar_prazo_prescricional("Seguro")
        assert p is not None
        assert p.prazo_anos == 1


class TestBuscarPrazoPrescricional:
    def test_exact_match(self) -> None:
        result = buscar_prazo_prescricional("Indenizatoria")
        assert result is not None
        assert result.tipo_acao == "Indenizatoria"

    def test_case_insensitive(self) -> None:
        result = buscar_prazo_prescricional("indenizatoria")
        assert result is not None

    def test_partial_match(self) -> None:
        result = buscar_prazo_prescricional("danos")
        assert result is not None
        assert "dano" in result.tipo_acao.lower()

    def test_not_found(self) -> None:
        result = buscar_prazo_prescricional("xyznonexistent")
        assert result is None

    def test_trabalhista_bienal(self) -> None:
        result = buscar_prazo_prescricional("Trabalhista bienal")
        assert result is not None
        assert result.prazo_anos == 2
