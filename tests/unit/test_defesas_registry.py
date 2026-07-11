"""Tests for the procedural-defense catalog registry."""

from __future__ import annotations

import asyncio

from juris.defesas.analyzer import DefesaAnalyzer
from juris.defesas.context import ProcessoContext
from juris.defesas.models import CodigoProcessual, TipoDefesa
from juris.defesas.registry import codigo_for_context, institutos_by_tipo, institutos_for_context


def test_registry_infers_cpc_clt_cpp_catalogs() -> None:
    civil = ProcessoContext(numero_cnj="1", tribunal="tjmg", classe="Cobranca")

    assert codigo_for_context(civil) == CodigoProcessual.CPC
    assert (
        codigo_for_context(
            ProcessoContext(
                numero_cnj="2",
                tribunal="trt3",
                classe="Reclamacao trabalhista",
                ramo_justica="trabalho",
            )
        )
        == CodigoProcessual.CLT
    )
    assert (
        codigo_for_context(
            ProcessoContext(
                numero_cnj="3",
                tribunal="tjmg",
                classe="Acao penal",
                ramo_justica="penal",
                assuntos=["crime contra patrimonio"],
            )
        )
        == CodigoProcessual.CPP
    )


def test_registry_exposes_institutes_by_context_and_type() -> None:
    penal = ProcessoContext(numero_cnj="3", tribunal="tjmg", classe="Acao penal", ramo_justica="penal")

    catalog = institutos_for_context(penal)
    prescricao_penal = institutos_by_tipo(TipoDefesa.PRESCRICAO, codigo=CodigoProcessual.CPP)

    assert any(inst.codigo_processual == CodigoProcessual.CPP for inst in catalog)
    assert any(inst.nome == "Prescricao penal" for inst in prescricao_penal)


def test_defesa_analyzer_records_catalog_consulted() -> None:
    ctx = ProcessoContext(
        numero_cnj="0001234-56.2026.5.03.0001",
        tribunal="trt3",
        classe="Reclamacao trabalhista",
        ramo_justica="trabalho",
        assuntos=["verbas rescisorias"],
    )

    report = asyncio.run(DefesaAnalyzer().analyze(ctx))

    assert report.codigos_consultados == ["CLT"]
    assert "Prescricao bienal trabalhista" in report.institutos_consultados
    assert "Catálogo consultado: CLT" in report.summary
