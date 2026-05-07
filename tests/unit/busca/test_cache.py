"""Tests for juris.busca.cache."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from juris.busca.cache import BuscaCache
from juris.busca.models import (
    BuscaRequest,
    FonteOrigem,
    RelatoriosBusca,
    ResultadoConsolidado,
)


def _make_relatorio(request: BuscaRequest) -> RelatoriosBusca:
    return RelatoriosBusca(
        request=request,
        resultados=[
            ResultadoConsolidado(
                numero_cnj="0000001-00.2024.8.26.0100",
                tribunal="TJSP",
                classe="Procedimento Comum",
                assunto="Direito Civil",
                orgao_julgador="1ª Vara",
                data_ajuizamento="01/01/2024",
                grau="1",
                ultima_atualizacao="",
                fontes=[FonteOrigem.ESAJ, FonteOrigem.DATAJUD],
                confianca=0.65,
                enriquecido=True,
                movimentos_count=5,
                valor_causa=10000.0,
            )
        ],
        total_encontrado=1,
        tribunais_consultados=10,
        tribunais_com_erro=["tjac"],
        canais_usados=[FonteOrigem.ESAJ, FonteOrigem.DATAJUD],
        duracao_segundos=2.5,
    )


class TestBuscaCache:
    def test_put_and_get(self) -> None:
        cache = BuscaCache(ttl_seconds=3600)
        req = BuscaRequest(nome="FULANO")
        rel = _make_relatorio(req)

        cache.put(req, rel)
        result = cache.get(req)

        assert result is not None
        assert result.total_encontrado == 1
        assert result.do_cache is True
        assert len(result.resultados) == 1
        assert result.resultados[0].confianca == 0.65

    def test_cache_miss(self) -> None:
        cache = BuscaCache()
        req = BuscaRequest(nome="NINGUEM")
        assert cache.get(req) is None

    def test_ttl_expiry(self) -> None:
        cache = BuscaCache(ttl_seconds=1)
        req = BuscaRequest(nome="FULANO")
        rel = _make_relatorio(req)

        cache.put(req, rel)

        # Patch time.time to simulate expiry
        with patch("juris.busca.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 10
            result = cache.get(req)

        assert result is None

    def test_invalidate(self) -> None:
        cache = BuscaCache()
        req = BuscaRequest(nome="FULANO")
        rel = _make_relatorio(req)

        cache.put(req, rel)
        assert cache.get(req) is not None

        cache.invalidate(req)
        assert cache.get(req) is None

    def test_key_normalization(self) -> None:
        cache = BuscaCache()
        req1 = BuscaRequest(nome="FULANO", cpf="123.456.789-00")
        req2 = BuscaRequest(nome="fulano", cpf="12345678900")
        rel = _make_relatorio(req1)

        cache.put(req1, rel)
        result = cache.get(req2)

        assert result is not None

    def test_fontes_preserved(self) -> None:
        cache = BuscaCache()
        req = BuscaRequest(nome="FULANO")
        rel = _make_relatorio(req)

        cache.put(req, rel)
        result = cache.get(req)

        assert result is not None
        assert result.canais_usados == [FonteOrigem.ESAJ, FonteOrigem.DATAJUD]
        assert result.resultados[0].fontes == [FonteOrigem.ESAJ, FonteOrigem.DATAJUD]

    def test_valor_causa_preserved(self) -> None:
        cache = BuscaCache()
        req = BuscaRequest(nome="FULANO")
        rel = _make_relatorio(req)

        cache.put(req, rel)
        result = cache.get(req)

        assert result is not None
        assert result.resultados[0].valor_causa == 10000.0
        assert result.resultados[0].movimentos_count == 5

    def test_overwrite(self) -> None:
        cache = BuscaCache()
        req = BuscaRequest(nome="FULANO")
        rel1 = _make_relatorio(req)

        cache.put(req, rel1)

        rel2 = RelatoriosBusca(
            request=req, resultados=[], total_encontrado=0,
            tribunais_consultados=0, tribunais_com_erro=[],
            canais_usados=[], duracao_segundos=0.0,
        )
        cache.put(req, rel2)

        result = cache.get(req)
        assert result is not None
        assert result.total_encontrado == 0
