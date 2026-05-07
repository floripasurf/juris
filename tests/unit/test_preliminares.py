"""Tests for defesas.preliminares — Art. 337 CPC checklist."""

from __future__ import annotations

from juris.defesas.context import ProcessoContext
from juris.defesas.models import TipoDefesa
from juris.defesas.preliminares import identificar_preliminares


def _make_context(**kwargs) -> ProcessoContext:
    defaults = {
        "numero_cnj": "0000000-00.2024.8.13.0000",
        "tribunal": "tjmg",
        "classe": "Acao de Cobranca",
    }
    defaults.update(kwargs)
    return ProcessoContext(**defaults)


class TestIdentificarPreliminares:
    def test_returns_all_six_checks(self) -> None:
        ctx = _make_context()
        results = identificar_preliminares(ctx)
        assert len(results) == 6

    def test_all_types_covered(self) -> None:
        ctx = _make_context()
        results = identificar_preliminares(ctx)
        tipos = {r.tipo for r in results}
        expected = {
            TipoDefesa.COISA_JULGADA,
            TipoDefesa.LITISPENDENCIA,
            TipoDefesa.INCOMPETENCIA,
            TipoDefesa.INEPCIA,
            TipoDefesa.ILEGITIMIDADE,
            TipoDefesa.FALTA_INTERESSE,
        }
        assert tipos == expected

    def test_coisa_julgada_with_transito(self) -> None:
        ctx = _make_context(
            movimentos=[{"codigo": 970, "data": "2024-01-01"}],
        )
        results = identificar_preliminares(ctx)
        coisa = next(r for r in results if r.tipo == TipoDefesa.COISA_JULGADA)
        assert coisa.aplicavel is True
        assert "502" in coisa.base_legal

    def test_coisa_julgada_without_transito(self) -> None:
        ctx = _make_context(movimentos=[{"codigo": 581, "data": "2024-01-01"}])
        results = identificar_preliminares(ctx)
        coisa = next(r for r in results if r.tipo == TipoDefesa.COISA_JULGADA)
        assert coisa.aplicavel is False

    def test_incompetencia_trabalho_in_civel(self) -> None:
        ctx = _make_context(
            ramo_justica="trabalho",
            tribunal="tjmg",
        )
        results = identificar_preliminares(ctx)
        incomp = next(r for r in results if r.tipo == TipoDefesa.INCOMPETENCIA)
        assert incomp.aplicavel is True

    def test_incompetencia_civel_in_trt(self) -> None:
        ctx = _make_context(
            ramo_justica="civel",
            tribunal="trt3",
        )
        results = identificar_preliminares(ctx)
        incomp = next(r for r in results if r.tipo == TipoDefesa.INCOMPETENCIA)
        assert incomp.aplicavel is True

    def test_no_incompetencia_normal(self) -> None:
        ctx = _make_context(
            ramo_justica="civel",
            tribunal="tjmg",
        )
        results = identificar_preliminares(ctx)
        incomp = next(r for r in results if r.tipo == TipoDefesa.INCOMPETENCIA)
        assert incomp.aplicavel is False

    def test_inepcia_no_assuntos(self) -> None:
        ctx = _make_context(assuntos=[])
        results = identificar_preliminares(ctx)
        inepcia = next(r for r in results if r.tipo == TipoDefesa.INEPCIA)
        assert inepcia.aplicavel is True

    def test_inepcia_with_assuntos(self) -> None:
        ctx = _make_context(assuntos=["Cobranca"])
        results = identificar_preliminares(ctx)
        inepcia = next(r for r in results if r.tipo == TipoDefesa.INEPCIA)
        assert inepcia.aplicavel is False

    def test_litispendencia_always_needs_manual_check(self) -> None:
        ctx = _make_context()
        results = identificar_preliminares(ctx)
        litis = next(r for r in results if r.tipo == TipoDefesa.LITISPENDENCIA)
        assert litis.aplicavel is False
        assert litis.confianca <= 0.5
