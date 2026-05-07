"""Tests for juris.busca.enrichment."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from juris.busca.enrichment import enrich_batch, enrich_resultado
from juris.busca.models import FonteOrigem, ResultadoConsolidado

_DATAJUD_SOURCE = {
    "numeroProcesso": "50823514020178130024",
    "classe": {"nome": "Procedimento Comum"},
    "assuntos": [{"nome": "Responsabilidade Civil"}],
    "movimentos": [
        {"dataHora": "2024-01-01T10:00:00.000Z", "nome": "Distribuição", "codigo": 26},
        {"dataHora": "2024-02-01T10:00:00.000Z", "nome": "Juntada de Petição", "codigo": 581},
    ],
    "valorCausa": {"valor": 50000.0},
}


def _make_resultado(**kwargs: object) -> ResultadoConsolidado:
    defaults = {
        "numero_cnj": "5082351-40.2017.8.13.0024",
        "tribunal": "tjmg",
        "classe": "Procedimento Comum",
        "assunto": "",
        "orgao_julgador": "",
        "data_ajuizamento": "",
        "grau": "1",
        "ultima_atualizacao": "",
        "fontes": [FonteOrigem.ESAJ],
    }
    defaults.update(kwargs)
    return ResultadoConsolidado(**defaults)  # type: ignore[arg-type]


class TestEnrichResultado:
    @pytest.mark.asyncio
    async def test_successful_enrichment(self) -> None:
        r = _make_resultado()
        with patch("juris.busca.enrichment.consultar_processo", return_value=_DATAJUD_SOURCE):
            enriched = await enrich_resultado(r)

        assert enriched.enriquecido is True
        assert enriched.movimentos_count == 2
        assert enriched.valor_causa == 50000.0
        assert enriched.dados_datajud is not None

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        r = _make_resultado()
        with patch("juris.busca.enrichment.consultar_processo", return_value=None):
            enriched = await enrich_resultado(r)

        assert enriched.enriquecido is False
        assert enriched.dados_datajud is None

    @pytest.mark.asyncio
    async def test_api_error(self) -> None:
        r = _make_resultado()
        with patch("juris.busca.enrichment.consultar_processo", side_effect=Exception("timeout")):
            enriched = await enrich_resultado(r)

        assert enriched.enriquecido is False

    @pytest.mark.asyncio
    async def test_valor_causa_numeric(self) -> None:
        source = {**_DATAJUD_SOURCE, "valorCausa": 75000.0}
        r = _make_resultado()
        with patch("juris.busca.enrichment.consultar_processo", return_value=source):
            enriched = await enrich_resultado(r)

        assert enriched.valor_causa == 75000.0


class TestEnrichBatch:
    @pytest.mark.asyncio
    async def test_batch_enrichment(self) -> None:
        results = [_make_resultado(numero_cnj=f"000000{i}-00.2024.8.13.0024") for i in range(3)]
        with patch("juris.busca.enrichment.consultar_processo", return_value=_DATAJUD_SOURCE):
            enriched = await enrich_batch(results, max_concurrent=2)

        assert len(enriched) == 3
        assert all(r.enriquecido for r in enriched)

    @pytest.mark.asyncio
    async def test_empty_batch(self) -> None:
        enriched = await enrich_batch([])
        assert enriched == []

    @pytest.mark.asyncio
    async def test_partial_failure(self) -> None:
        results = [_make_resultado(numero_cnj=f"000000{i}-00.2024.8.13.0024") for i in range(3)]

        call_count = 0

        def _mock_consultar(*args: object, **kwargs: object) -> dict | None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("timeout")
            return _DATAJUD_SOURCE

        with patch("juris.busca.enrichment.consultar_processo", side_effect=_mock_consultar):
            enriched = await enrich_batch(results)

        assert len(enriched) == 3
        enriched_count = sum(1 for r in enriched if r.enriquecido)
        assert enriched_count == 2

    @pytest.mark.asyncio
    async def test_preserves_order(self) -> None:
        results = [_make_resultado(numero_cnj=f"000000{i}-00.2024.8.13.0024") for i in range(5)]
        with patch("juris.busca.enrichment.consultar_processo", return_value=_DATAJUD_SOURCE):
            enriched = await enrich_batch(results)

        for i, r in enumerate(enriched):
            assert r.numero_cnj == f"000000{i}-00.2024.8.13.0024"
