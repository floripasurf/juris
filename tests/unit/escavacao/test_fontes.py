"""Tests for the source-confidence ranking signal (frente C slice 3)."""

from __future__ import annotations

from juris.escavacao.fontes import fonte_confianca


def test_full_text_sources_outrank_the_datajud_trail() -> None:
    # the real acórdão sources carry more confidence than the partial trail
    assert fonte_confianca("tst") > fonte_confianca("datajud")
    assert fonte_confianca("esaj") > fonte_confianca("datajud")


def test_unknown_source_is_low_but_nonzero() -> None:
    assert 0.0 < fonte_confianca("fonte-desconhecida") < fonte_confianca("tst")


def test_confidence_is_bounded() -> None:
    assert fonte_confianca("tst") <= 1.0
    assert fonte_confianca("datajud") >= 0.0
