"""Tests for TPU movement code mapper."""

from juris.mni.tpu import CategoriaSemantica, categorize_movement, is_actionable


class TestCategorizaMovimento:
    def test_sentenca(self) -> None:
        assert categorize_movement(132) == CategoriaSemantica.SENTENCA

    def test_decisao_recorrivel(self) -> None:
        assert categorize_movement(193) == CategoriaSemantica.DECISAO_RECORRIVEL

    def test_audiencia(self) -> None:
        assert categorize_movement(51) == CategoriaSemantica.PAUTA_MARCADA

    def test_juntada_is_noise_like(self) -> None:
        assert categorize_movement(246) == CategoriaSemantica.JUNTADA_DOCUMENTO

    def test_transito_julgado(self) -> None:
        assert categorize_movement(970) == CategoriaSemantica.TRANSITO_JULGADO

    def test_unknown_code_is_unclassified(self) -> None:
        assert categorize_movement(99999) == CategoriaSemantica.UNCLASSIFIED

    def test_acordo(self) -> None:
        assert categorize_movement(1051) == CategoriaSemantica.ACORDO


class TestIsActionable:
    def test_sentenca_is_actionable(self) -> None:
        assert is_actionable(CategoriaSemantica.SENTENCA) is True

    def test_noise_is_not_actionable(self) -> None:
        assert is_actionable(CategoriaSemantica.NOISE) is False

    def test_juntada_is_not_actionable(self) -> None:
        assert is_actionable(CategoriaSemantica.JUNTADA_DOCUMENTO) is False

    def test_intimacao_is_actionable(self) -> None:
        assert is_actionable(CategoriaSemantica.INTIMACAO) is True
