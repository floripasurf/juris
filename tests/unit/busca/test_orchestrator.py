"""Tests for juris.busca.orchestrator."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.busca.abc import SearchChannel
from juris.busca.models import (
    BuscaRequest,
    FonteOrigem,
    ResultadoBusca,
    ResultadoConsolidado,
)
from juris.busca.orchestrator import SearchOrchestrator
from juris.busca.registry import ChannelRegistry


def _make_resultado(
    cnj: str = "0000001-00.2024.8.26.0100",
    tribunal: str = "TJSP",
    fonte: FonteOrigem = FonteOrigem.ESAJ,
    **kwargs: object,
) -> ResultadoBusca:
    defaults = {
        "numero_cnj": cnj,
        "tribunal": tribunal,
        "fonte": fonte,
        "classe": "Procedimento Comum",
        "assunto": "Direito Civil",
        "orgao_julgador": "1ª Vara",
        "data_ajuizamento": "01/01/2024",
        "grau": "1",
        "ultima_atualizacao": "",
    }
    defaults.update(kwargs)
    return ResultadoBusca(**defaults)  # type: ignore[arg-type]


def _mock_channel(
    name: FonteOrigem,
    tribunais: list[str],
    results: list[ResultadoBusca] | None = None,
) -> SearchChannel:
    ch = MagicMock(spec=SearchChannel)
    ch.channel_name = name
    ch.supported_tribunais.return_value = tribunais
    ch.search_by_name = AsyncMock(return_value=results or [])
    ch.search_by_cpf = AsyncMock(return_value=results or [])
    ch.search_by_oab = AsyncMock(return_value=[])
    return ch


class TestSearchOrchestrator:
    @pytest.mark.asyncio
    async def test_basic_search(self) -> None:
        result = _make_resultado()
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert relatorio.total_encontrado == 1
        assert relatorio.resultados[0].numero_cnj == "0000001-00.2024.8.26.0100"
        assert FonteOrigem.ESAJ in relatorio.canais_usados

    @pytest.mark.asyncio
    async def test_dedup_by_cnj(self) -> None:
        cnj = "0000001-00.2024.8.26.0100"
        r1 = _make_resultado(cnj=cnj, fonte=FonteOrigem.ESAJ)
        r2 = _make_resultado(cnj=cnj, fonte=FonteOrigem.DATAJUD, classe="Outra Classe")

        ch1 = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [r1])
        ch2 = _mock_channel(FonteOrigem.DATAJUD, ["tjsp"], [r2])
        registry = ChannelRegistry(channels=[ch1, ch2])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert relatorio.total_encontrado == 1
        # ESAJ has higher priority, so its classe should win
        assert relatorio.resultados[0].classe == "Procedimento Comum"
        assert len(relatorio.resultados[0].fontes) == 2

    @pytest.mark.asyncio
    async def test_confidence_reliable_source(self) -> None:
        result = _make_resultado(fonte=FonteOrigem.ESAJ)
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert relatorio.resultados[0].confianca >= 0.5

    @pytest.mark.asyncio
    async def test_confidence_datajud_only(self) -> None:
        result = _make_resultado(fonte=FonteOrigem.DATAJUD)
        ch = _mock_channel(FonteOrigem.DATAJUD, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert relatorio.resultados[0].confianca == 0.3

    @pytest.mark.asyncio
    async def test_confidence_cpf_bonus(self) -> None:
        result = _make_resultado(fonte=FonteOrigem.ESAJ)
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO", cpf="123.456.789-00"))

        assert relatorio.resultados[0].confianca >= 0.55

    @pytest.mark.asyncio
    async def test_confidence_corroboration_bonus(self) -> None:
        cnj = "0000001-00.2024.8.26.0100"
        r1 = _make_resultado(cnj=cnj, fonte=FonteOrigem.ESAJ)
        r2 = _make_resultado(cnj=cnj, fonte=FonteOrigem.DATAJUD)

        ch1 = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [r1])
        ch2 = _mock_channel(FonteOrigem.DATAJUD, ["tjsp"], [r2])
        registry = ChannelRegistry(channels=[ch1, ch2])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        # 0.5 (reliable) + 0.15 (1 extra source) = 0.65
        assert relatorio.resultados[0].confianca == 0.65

    @pytest.mark.asyncio
    async def test_polo_union(self) -> None:
        cnj = "0000001-00.2024.8.26.0100"
        r1 = _make_resultado(cnj=cnj, fonte=FonteOrigem.ESAJ, polo_ativo=["ALICE"])
        r2 = _make_resultado(cnj=cnj, fonte=FonteOrigem.DATAJUD, polo_ativo=["BOB"])

        ch1 = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [r1])
        ch2 = _mock_channel(FonteOrigem.DATAJUD, ["tjsp"], [r2])
        registry = ChannelRegistry(channels=[ch1, ch2])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert set(relatorio.resultados[0].polo_ativo) == {"ALICE", "BOB"}

    @pytest.mark.asyncio
    async def test_graceful_channel_failure(self) -> None:
        ok_result = _make_resultado()
        ch_ok = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [ok_result])

        ch_fail = MagicMock(spec=SearchChannel)
        ch_fail.channel_name = FonteOrigem.EPROC
        ch_fail.supported_tribunais.return_value = ["trf4"]
        ch_fail.search_by_name = AsyncMock(side_effect=Exception("network error"))
        ch_fail.search_by_cpf = AsyncMock(side_effect=Exception("network error"))
        ch_fail.search_by_oab = AsyncMock(return_value=[])

        registry = ChannelRegistry(channels=[ch_ok, ch_fail])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert relatorio.total_encontrado == 1
        assert "trf4" in relatorio.tribunais_com_erro

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="NINGUEM"))

        assert relatorio.total_encontrado == 0
        assert relatorio.resultados == []

    @pytest.mark.asyncio
    async def test_tribunal_filter(self) -> None:
        r1 = _make_resultado(tribunal="TJSP")
        r2 = _make_resultado(cnj="0000002-00.2024.8.13.0024", tribunal="TJMG")

        ch1 = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [r1])
        ch2 = _mock_channel(FonteOrigem.EJEF, ["tjmg"], [r2])
        registry = ChannelRegistry(channels=[ch1, ch2])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(
            BuscaRequest(nome="FULANO", tribunais=["tjsp"])
        )

        assert relatorio.total_encontrado == 1
        assert relatorio.resultados[0].tribunal == "TJSP"

    @pytest.mark.asyncio
    async def test_cpf_dispatches_cpf_search(self) -> None:
        result = _make_resultado()
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        await orchestrator.search(BuscaRequest(cpf="123.456.789-00"))

        ch.search_by_cpf.assert_called()

    @pytest.mark.asyncio
    async def test_oab_dispatches_oab_search(self) -> None:
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        await orchestrator.search(BuscaRequest(oab="SP123456"))

        ch.search_by_oab.assert_called()

    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        from juris.busca.models import RelatoriosBusca

        req = BuscaRequest(nome="CACHED")
        cached_rel = RelatoriosBusca(
            request=req, resultados=[], total_encontrado=0,
            tribunais_consultados=0, tribunais_com_erro=[],
            canais_usados=[], duracao_segundos=0.1, do_cache=True,
        )
        mock_cache = MagicMock()
        mock_cache.get.return_value = cached_rel

        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=mock_cache, enrich=False)
        relatorio = await orchestrator.search(req)

        assert relatorio.do_cache is True
        ch.search_by_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_then_put(self) -> None:
        result = _make_resultado()
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        orchestrator = SearchOrchestrator(registry=registry, cache=mock_cache, enrich=False)
        await orchestrator.search(BuscaRequest(nome="FULANO"))

        mock_cache.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_sorted_by_confidence(self) -> None:
        r1 = _make_resultado(cnj="0000001-00.2024.8.26.0100", fonte=FonteOrigem.DATAJUD)
        r2 = _make_resultado(cnj="0000002-00.2024.8.26.0100", fonte=FonteOrigem.ESAJ)

        ch1 = _mock_channel(FonteOrigem.DATAJUD, ["tjsp"], [r1])
        ch2 = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [r2])
        registry = ChannelRegistry(channels=[ch1, ch2])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert len(relatorio.resultados) == 2
        assert relatorio.resultados[0].confianca >= relatorio.resultados[1].confianca

    @pytest.mark.asyncio
    async def test_enrichment_enabled(self) -> None:
        result = _make_resultado()
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        with patch("juris.busca.orchestrator.enrich_batch") as mock_enrich:
            mock_enrich.return_value = [
                ResultadoConsolidado(
                    numero_cnj="0000001-00.2024.8.26.0100",
                    tribunal="TJSP", classe="", assunto="",
                    orgao_julgador="", data_ajuizamento="", grau="1",
                    ultima_atualizacao="",
                    fontes=[FonteOrigem.ESAJ],
                    enriquecido=True, movimentos_count=10,
                )
            ]

            orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=True)
            relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

            mock_enrich.assert_called_once()
            assert relatorio.resultados[0].enriquecido is True

    @pytest.mark.asyncio
    async def test_enrichment_disabled(self) -> None:
        result = _make_resultado()
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [result])
        registry = ChannelRegistry(channels=[ch])

        with patch("juris.busca.orchestrator.enrich_batch") as mock_enrich:
            orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
            await orchestrator.search(BuscaRequest(nome="FULANO"))

            mock_enrich.assert_not_called()

    @pytest.mark.asyncio
    async def test_duration_recorded(self) -> None:
        ch = _mock_channel(FonteOrigem.ESAJ, ["tjsp"], [])
        registry = ChannelRegistry(channels=[ch])

        orchestrator = SearchOrchestrator(registry=registry, cache=None, enrich=False)
        relatorio = await orchestrator.search(BuscaRequest(nome="FULANO"))

        assert relatorio.duracao_segundos >= 0
