"""Tests for expanded TPU mapping."""

from __future__ import annotations

from juris.mni.tpu import (
    CategoriaSemantica,
    Urgencia,
    categorize_movement,
    get_entry,
    get_urgency,
    is_actionable,
    is_high_confidence,
    tpu_coverage_stats,
)


class TestCategorizeMovement:
    def test_sentenca(self) -> None:
        assert categorize_movement(132) == CategoriaSemantica.SENTENCA

    def test_decisao(self) -> None:
        assert categorize_movement(193) == CategoriaSemantica.DECISAO_RECORRIVEL

    def test_tutela(self) -> None:
        assert categorize_movement(334) == CategoriaSemantica.TUTELA

    def test_citacao(self) -> None:
        assert categorize_movement(12) == CategoriaSemantica.CITACAO

    def test_intimacao(self) -> None:
        assert categorize_movement(14) == CategoriaSemantica.INTIMACAO

    def test_prazo(self) -> None:
        assert categorize_movement(85) == CategoriaSemantica.PRAZO_ABERTO

    def test_recurso(self) -> None:
        assert categorize_movement(197) == CategoriaSemantica.RECURSO

    def test_noise(self) -> None:
        assert categorize_movement(11) == CategoriaSemantica.NOISE

    def test_pericia(self) -> None:
        assert categorize_movement(470) == CategoriaSemantica.PERICIA

    def test_cumprimento(self) -> None:
        assert categorize_movement(480) == CategoriaSemantica.CUMPRIMENTO

    def test_execucao(self) -> None:
        assert categorize_movement(481) == CategoriaSemantica.EXECUCAO

    def test_unknown_returns_unclassified(self) -> None:
        assert categorize_movement(99999) == CategoriaSemantica.UNCLASSIFIED


class TestUrgency:
    def test_sentenca_is_critica(self) -> None:
        assert get_urgency(132) == Urgencia.CRITICA

    def test_citacao_is_alta(self) -> None:
        assert get_urgency(12) == Urgencia.ALTA

    def test_audiencia_is_media(self) -> None:
        assert get_urgency(51) == Urgencia.MEDIA

    def test_juntada_is_baixa(self) -> None:
        assert get_urgency(246) == Urgencia.BAIXA

    def test_noise_is_nenhuma(self) -> None:
        assert get_urgency(11) == Urgencia.NENHUMA

    def test_unknown_defaults_to_media(self) -> None:
        assert get_urgency(99999) == Urgencia.MEDIA


class TestGetEntry:
    def test_known_code(self) -> None:
        entry = get_entry(132)
        assert entry is not None
        assert entry.codigo == 132
        assert entry.categoria == CategoriaSemantica.SENTENCA
        assert entry.requer_acao is True

    def test_unknown_code(self) -> None:
        assert get_entry(99999) is None

    def test_noise_entry_not_actionable(self) -> None:
        entry = get_entry(11)
        assert entry is not None
        assert entry.requer_acao is False


class TestIsActionable:
    def test_sentenca_actionable(self) -> None:
        assert is_actionable(CategoriaSemantica.SENTENCA)

    def test_noise_not_actionable(self) -> None:
        assert not is_actionable(CategoriaSemantica.NOISE)

    def test_tutela_actionable(self) -> None:
        assert is_actionable(CategoriaSemantica.TUTELA)

    def test_unclassified_not_actionable(self) -> None:
        assert not is_actionable(CategoriaSemantica.UNCLASSIFIED)


class TestHighConfidence:
    def test_sentenca_high_confidence(self) -> None:
        assert is_high_confidence(132)

    def test_noise_high_confidence(self) -> None:
        assert is_high_confidence(11)

    def test_unknown_not_high_confidence(self) -> None:
        assert not is_high_confidence(99999)

    def test_pericia_not_high_confidence(self) -> None:
        # Pericia is not in HIGH_CONFIDENCE_CATEGORIES
        assert not is_high_confidence(470)


class TestCoverageStats:
    def test_returns_dict(self) -> None:
        stats = tpu_coverage_stats()
        assert "total_codes" in stats
        assert stats["total_codes"] >= 120  # We have ~150 codes

    def test_has_all_categories(self) -> None:
        stats = tpu_coverage_stats()
        cats = stats["by_category"]
        assert "noise" in cats
        assert "sentenca" in cats
        assert cats["noise"] >= 15  # Plenty of noise codes
