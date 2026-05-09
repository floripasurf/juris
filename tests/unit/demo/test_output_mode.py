"""Tests for juris.demo.output_mode — Sprint 17 mode selection."""

from __future__ import annotations

import pytest

from juris.demo.output_mode import (
    DRAFT_FILENAME,
    MINUTA_SUGERIDA_BANNER,
    RASCUNHO_PESQUISA_BANNER,
    OutputMode,
    banner_for,
    draft_filename,
    label_for,
)


class TestOutputModeEnum:
    def test_minuta_value(self) -> None:
        assert OutputMode.MINUTA_SUGERIDA.value == "minuta-sugerida"

    def test_rascunho_value(self) -> None:
        assert OutputMode.RASCUNHO_PESQUISA.value == "rascunho-pesquisa"

    def test_string_subclass(self) -> None:
        # ``str`` subclass so it serialises naturally in JSON manifests.
        assert isinstance(OutputMode.MINUTA_SUGERIDA, str)

    def test_round_trip_from_value(self) -> None:
        assert OutputMode("minuta-sugerida") is OutputMode.MINUTA_SUGERIDA
        assert OutputMode("rascunho-pesquisa") is OutputMode.RASCUNHO_PESQUISA

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            OutputMode("nonexistent-mode")


class TestBannerFor:
    def test_minuta_banner_string(self) -> None:
        assert banner_for(OutputMode.MINUTA_SUGERIDA) == MINUTA_SUGERIDA_BANNER

    def test_rascunho_banner_string(self) -> None:
        assert banner_for(OutputMode.RASCUNHO_PESQUISA) == RASCUNHO_PESQUISA_BANNER

    def test_minuta_banner_marks_review_mandatory(self) -> None:
        # The MINUTA banner must communicate mandatory lawyer review so the
        # operator/lawyer cannot mistake the artifact for a finished petition.
        banner = banner_for(OutputMode.MINUTA_SUGERIDA)
        assert "MINUTA SUGERIDA" in banner
        assert "REVIS" in banner.upper()  # "REVISÃO" / "REVISAR"
        assert "OAB" in banner

    def test_rascunho_banner_marks_non_filable(self) -> None:
        # The RASCUNHO banner must be unmistakable about non-filability.
        banner = banner_for(OutputMode.RASCUNHO_PESQUISA)
        assert "RASCUNHO DE PESQUISA" in banner
        assert "NÃO" in banner.upper() or "NAO" in banner.upper()
        assert "PROTOCOLO" in banner.upper()


class TestLabelFor:
    def test_minuta_label(self) -> None:
        assert label_for(OutputMode.MINUTA_SUGERIDA) == "MINUTA SUGERIDA"

    def test_rascunho_label(self) -> None:
        assert label_for(OutputMode.RASCUNHO_PESQUISA) == "RASCUNHO DE PESQUISA"


class TestDraftFilename:
    def test_minuta_filename(self) -> None:
        assert draft_filename(OutputMode.MINUTA_SUGERIDA) == "draft.md"

    def test_rascunho_filename_distinct_from_draft(self) -> None:
        # Codex constraint: RASCUNHO mode must not write to draft.md so it
        # cannot be confused with a fileable petition on the filesystem.
        assert draft_filename(OutputMode.RASCUNHO_PESQUISA) != "draft.md"
        assert draft_filename(OutputMode.RASCUNHO_PESQUISA) == "rascunho-pesquisa.md"

    def test_filename_map_covers_all_modes(self) -> None:
        # Guard against forgetting to update DRAFT_FILENAME when adding modes.
        for mode in OutputMode:
            assert mode in DRAFT_FILENAME
