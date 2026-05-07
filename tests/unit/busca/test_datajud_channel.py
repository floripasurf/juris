"""Tests for juris.busca.channels.datajud."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from juris.busca.channels.datajud import DataJudChannel, _format_cnj, _to_resultado
from juris.busca.models import FonteOrigem

_DATAJUD_HIT = {
    "numeroProcesso": "50823514020178130024",
    "_tribunal_id": "tjmg",
    "classe": {"nome": "Procedimento Comum"},
    "assuntos": [{"nome": "Responsabilidade Civil"}],
    "orgaoJulgador": {"nome": "35ª Vara Cível"},
    "dataAjuizamento": "2017-06-19T13:20:04.000Z",
    "grau": "G1",
    "dataHoraUltimaAtualizacao": "2024-01-15T10:00:00.000Z",
}


class TestFormatCnj:
    def test_20_digit(self) -> None:
        assert _format_cnj("50823514020178130024") == "5082351-40.2017.8.13.0024"

    def test_already_formatted(self) -> None:
        assert _format_cnj("5082351-40.2017.8.13.0024") == "5082351-40.2017.8.13.0024"

    def test_short_string(self) -> None:
        assert _format_cnj("12345") == "12345"


class TestToResultado:
    def test_converts_hit(self) -> None:
        r = _to_resultado(_DATAJUD_HIT)
        assert r.numero_cnj == "5082351-40.2017.8.13.0024"
        assert r.tribunal == "TJMG"
        assert r.fonte == FonteOrigem.DATAJUD
        assert r.classe == "Procedimento Comum"
        assert "Responsabilidade Civil" in r.assunto
        assert r.orgao_julgador == "35ª Vara Cível"

    def test_missing_fields(self) -> None:
        r = _to_resultado({"numeroProcesso": "12345", "_tribunal_id": "tjsp"})
        assert r.numero_cnj == "12345"
        assert r.classe == ""


class TestDataJudChannel:
    def setup_method(self) -> None:
        self.channel = DataJudChannel()

    def test_channel_name(self) -> None:
        assert self.channel.channel_name == FonteOrigem.DATAJUD

    def test_supported_tribunais_includes_many(self) -> None:
        tribunais = self.channel.supported_tribunais()
        assert len(tribunais) > 50
        assert "tjsp" in tribunais
        assert "stj" in tribunais

    @pytest.mark.asyncio
    async def test_search_by_name(self) -> None:
        with patch("juris.busca.channels.datajud.buscar_parte_tribunal", return_value=[_DATAJUD_HIT]):
            results = await self.channel.search_by_name("tjmg", "FULANO")

        assert len(results) == 1
        assert results[0].fonte == FonteOrigem.DATAJUD

    @pytest.mark.asyncio
    async def test_search_by_cpf(self) -> None:
        with patch("juris.busca.channels.datajud.buscar_parte_tribunal", return_value=[_DATAJUD_HIT]):
            results = await self.channel.search_by_cpf("tjmg", "123.456.789-00")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_by_oab_returns_empty(self) -> None:
        results = await self.channel.search_by_oab("tjmg", "MG123456")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self) -> None:
        with patch("juris.busca.channels.datajud.buscar_parte_tribunal", side_effect=Exception("API error")):
            results = await self.channel.search_by_name("tjmg", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self) -> None:
        with patch("juris.busca.channels.datajud.busca_circuit_breaker") as mock_cb:
            mock_cb.check.side_effect = RuntimeError("Circuit open")
            results = await self.channel.search_by_name("tjmg", "FULANO")

        assert results == []
