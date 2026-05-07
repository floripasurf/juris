"""Tests for juris.busca.channels.esaj."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from juris.busca.channels.esaj import EsajChannel, _parse_esaj_results
from juris.busca.models import FonteOrigem

# Minimal ESAJ HTML fixture that produces one result.
_ESAJ_HTML = """
<html>
<div id="listagemDeProcessos">
  <a href="abrirConsultaExterna.do?processo.codigo=ABC123">
    1234567-89.2024.8.26.0100
  </a>
  <span class="classeProcesso">Procedimento Comum Cível</span>
  <span class="assuntoPrincipalProcesso">Indenização por Dano Moral</span>
  <span class="dataLocalDistribuicaoProcesso">15/03/2024 - 1ª Vara Cível</span>
  <span class="tipoDeParticipacao">Autor</span>
  <span class="nomeParte">FULANO DE TAL</span>
</div>
</html>
"""

_ESAJ_NO_RESULTS = '<html>Não existem informações disponíveis para os dados informados</html>'
_ESAJ_TOO_MANY = '<html>Foram encontrados muitos processos</html>'


class TestParseEsajResults:
    def test_parse_single_result(self) -> None:
        results = _parse_esaj_results(_ESAJ_HTML, "tjsp", "1g")
        assert len(results) == 1
        r = results[0]
        assert r.numero_cnj == "1234567-89.2024.8.26.0100"
        assert r.tribunal == "TJSP"
        assert r.fonte == FonteOrigem.ESAJ
        assert r.classe == "Procedimento Comum Cível"
        assert r.assunto == "Indenização por Dano Moral"
        assert r.orgao_julgador == "1ª Vara Cível"
        assert r.data_ajuizamento == "15/03/2024"
        assert r.grau == "1"
        assert "FULANO DE TAL" in r.polo_ativo

    def test_parse_empty_html(self) -> None:
        results = _parse_esaj_results("<html></html>", "tjsp", "1g")
        assert results == []

    def test_parse_2g_grau(self) -> None:
        results = _parse_esaj_results(_ESAJ_HTML, "tjsp", "2g")
        assert results[0].grau == "2"


class TestEsajChannel:
    def setup_method(self) -> None:
        self.channel = EsajChannel()

    def test_channel_name(self) -> None:
        assert self.channel.channel_name == FonteOrigem.ESAJ

    def test_supported_tribunais(self) -> None:
        tribunais = self.channel.supported_tribunais()
        assert "tjsp" in tribunais
        assert "tjba" in tribunais  # new
        assert "tjrr" in tribunais  # new
        assert len(tribunais) == 12

    @pytest.mark.asyncio
    async def test_search_by_name_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = _ESAJ_HTML

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjsp", "FULANO")

        assert len(results) >= 1
        assert results[0].fonte == FonteOrigem.ESAJ

    @pytest.mark.asyncio
    async def test_search_unsupported_tribunal(self) -> None:
        results = await self.channel.search_by_name("stf", "FULANO")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_by_cpf(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = _ESAJ_HTML

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_cpf("tjsp", "123.456.789-00")

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_by_oab(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = _ESAJ_HTML

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_oab("tjsp", "SP123456")

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_no_results_message(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = _ESAJ_NO_RESULTS

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjsp", "NOBODY")

        assert results == []

    @pytest.mark.asyncio
    async def test_too_many_results_message(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = _ESAJ_TOO_MANY

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjsp", "SILVA")

        assert results == []

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty(self) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjsp", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_returns_empty(self) -> None:
        with patch("juris.busca.channels.esaj.busca_circuit_breaker") as mock_cb:
            mock_cb.check.side_effect = RuntimeError("Circuit open")
            results = await self.channel.search_by_name("tjsp", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_status_returns_empty(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = ""

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.esaj.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjsp", "FULANO")

        assert results == []
