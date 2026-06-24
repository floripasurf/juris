"""Health-aware resolution: skip providers whose circuit is open (ADR-0017)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from juris.busca.abc import SearchChannel
from juris.busca.models import BuscaRequest, FonteOrigem, ResultadoBusca
from juris.busca.orchestrator import SearchOrchestrator
from juris.busca.registry import ChannelRegistry
from juris.mni.retry import CircuitBreaker


def _result() -> ResultadoBusca:
    return ResultadoBusca(
        numero_cnj="0000001-00.2024.8.26.0100",
        tribunal="TJSP",
        fonte=FonteOrigem.ESAJ,
        classe="Procedimento Comum",
        assunto="Direito Civil",
        orgao_julgador="1ª Vara",
        data_ajuizamento="01/01/2024",
        grau="1",
        ultima_atualizacao="",
    )


def _channel(name: FonteOrigem, tribunais: list[str], *, results=None, fail: bool = False) -> SearchChannel:
    ch = MagicMock(spec=SearchChannel)
    ch.channel_name = name
    ch.supported_tribunais.return_value = tribunais
    side = AsyncMock(side_effect=RuntimeError("boom")) if fail else AsyncMock(return_value=results or [])
    ch.search_by_name = side
    ch.search_by_cpf = side
    ch.search_by_oab = side
    return ch


def _orch(channel, breaker: CircuitBreaker) -> SearchOrchestrator:
    return SearchOrchestrator(
        registry=ChannelRegistry([channel]), cache=None, enrich=False, circuit_breaker=breaker
    )


@pytest.mark.asyncio
async def test_open_circuit_channel_is_skipped_not_queried() -> None:
    breaker = CircuitBreaker(failure_threshold=1, window_seconds=300.0, recovery_seconds=120.0)
    breaker.record_failure("esaj:tjsp")  # threshold 1 → circuit opens

    ch = _channel(FonteOrigem.ESAJ, ["tjsp"], results=[_result()])
    relatorio = await _orch(ch, breaker).search(BuscaRequest(nome="ACME", tribunais=["tjsp"]))

    ch.search_by_name.assert_not_called()  # dead provider never queried
    assert "esaj:tjsp" in relatorio.provedores_pulados
    assert relatorio.total_encontrado == 0


@pytest.mark.asyncio
async def test_channel_failure_is_recorded_in_the_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=5, window_seconds=300.0, recovery_seconds=120.0)
    ch = _channel(FonteOrigem.ESAJ, ["tjsp"], fail=True)

    await _orch(ch, breaker).search(BuscaRequest(nome="ACME", tribunais=["tjsp"]))

    assert breaker.get_state("esaj:tjsp").failures >= 1


@pytest.mark.asyncio
async def test_healthy_channel_is_queried_normally() -> None:
    breaker = CircuitBreaker(failure_threshold=3, window_seconds=300.0, recovery_seconds=120.0)
    ch = _channel(FonteOrigem.ESAJ, ["tjsp"], results=[_result()])

    relatorio = await _orch(ch, breaker).search(BuscaRequest(nome="ACME", tribunais=["tjsp"]))

    assert relatorio.total_encontrado == 1
    assert relatorio.provedores_pulados == []
