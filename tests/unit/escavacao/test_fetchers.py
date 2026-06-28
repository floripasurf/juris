"""Tests for the escavação fetchers (Source Mesh adapters)."""

from __future__ import annotations

import pytest

from juris.escavacao.fetchers import DataJudEscavacaoFetcher
from juris.escavacao.queue import AlvoEscavacao


def _alvo(cnj: str, tribunal: str | None = "tjmg") -> AlvoEscavacao:
    return AlvoEscavacao(numero_cnj=cnj, origem_tema="STJ-1", prioridade=6.0, tribunal=tribunal)


def _source() -> dict:
    return {
        "classe": {"nome": "Apelação Cível"},
        "assuntos": [{"nome": "Dano Moral"}],
        "movimentos": [
            {"nome": "Distribuição", "dataHora": "2020-01-01T00:00:00"},
            {"nome": "Julgamento", "dataHora": "2021-06-01T00:00:00"},
        ],
    }


@pytest.mark.asyncio
async def test_builds_inteiro_teor_from_datajud_process() -> None:
    def fake_consultar(cnj: str, tribunal: str, **kw: object) -> dict:
        assert cnj == "5000000-00.2020.8.13.0024"
        return _source()

    fetcher = DataJudEscavacaoFetcher(consultar=fake_consultar)
    teor = await fetcher.fetch(_alvo("5000000-00.2020.8.13.0024"))

    assert teor is not None
    assert teor.fonte == "datajud"
    assert teor.origem_tema == "STJ-1"
    assert "Apelação Cível" in teor.texto
    assert "Julgamento" in teor.texto  # the movements trail is captured
    assert teor.metadata["movimentos"] == 2


@pytest.mark.asyncio
async def test_returns_none_when_process_not_found() -> None:
    fetcher = DataJudEscavacaoFetcher(consultar=lambda *a, **k: None)
    assert await fetcher.fetch(_alvo("X")) is None


@pytest.mark.asyncio
async def test_skips_target_without_tribunal() -> None:
    def _boom(*a: object, **k: object) -> dict:
        raise AssertionError("should not call DataJud without a tribunal")

    fetcher = DataJudEscavacaoFetcher(consultar=_boom)
    assert await fetcher.fetch(_alvo("X", tribunal=None)) is None


class _Fixed:
    """A fetcher that returns a fixed InteiroTeor (or None)."""

    def __init__(self, teor) -> None:
        self._teor = teor

    async def fetch(self, alvo):
        return self._teor


def _teor(cnj: str, fonte: str, *, parcial: bool):
    from juris.escavacao.executor import InteiroTeor

    return InteiroTeor(
        numero_cnj=cnj, texto=f"texto {fonte}", fonte=fonte, origem_tema="STJ-1",
        metadata={"parcial": parcial},
    )


@pytest.mark.asyncio
async def test_failover_prefers_complete_source_over_partial() -> None:
    from juris.escavacao.fetchers import FailoverFetcher

    partial = _Fixed(_teor("A", "datajud", parcial=True))
    full = _Fixed(_teor("A", "esaj-cjsg", parcial=False))
    # partial source listed first, but the complete acórdão must win
    fetcher = FailoverFetcher([partial, full])

    teor = await fetcher.fetch(_alvo("A"))
    assert teor is not None
    assert teor.fonte == "esaj-cjsg"  # provenance of the winning source
    assert teor.metadata["parcial"] is False


@pytest.mark.asyncio
async def test_failover_falls_back_to_partial_trail() -> None:
    from juris.escavacao.fetchers import FailoverFetcher

    fetcher = FailoverFetcher([_Fixed(None), _Fixed(_teor("A", "datajud", parcial=True))])
    teor = await fetcher.fetch(_alvo("A"))
    assert teor is not None
    assert teor.fonte == "datajud"  # the trail, when no complete source answered


@pytest.mark.asyncio
async def test_failover_returns_none_when_all_fail() -> None:
    from juris.escavacao.fetchers import FailoverFetcher

    assert await FailoverFetcher([_Fixed(None), _Fixed(None)]).fetch(_alvo("A")) is None
