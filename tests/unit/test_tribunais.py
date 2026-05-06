"""Tests for tribunal registry."""

import pytest

from juris.mni.tribunais import get_tribunal, list_tribunais


class TestTribunalRegistry:
    def test_get_existing_tribunal(self) -> None:
        t = get_tribunal("trt2")
        assert t.id == "trt2"
        assert "Sao Paulo" in t.nome

    def test_get_tribunal_case_insensitive(self) -> None:
        t = get_tribunal("TRT2")
        assert t.id == "trt2"

    def test_get_nonexistent_raises(self) -> None:
        with pytest.raises(KeyError, match="not found"):
            get_tribunal("nonexistent")

    def test_list_tribunais_not_empty(self) -> None:
        tribunais = list_tribunais()
        assert len(tribunais) >= 5
