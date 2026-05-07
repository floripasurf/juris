"""Tests for juris.busca.channels.eproc."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from juris.busca.channels.eproc import EprocChannel
from juris.busca.models import FonteOrigem

_TRF4_JSON = [
    {
        "numeroProcesso": "5000001-00.2024.4.04.7000",
        "classeProcessual": "Ação Civil Pública",
        "assunto": "Improbidade Administrativa",
        "orgaoJulgador": "1ª Vara Federal",
        "dataAjuizamento": "2024-01-15",
        "grau": "1",
        "ultimaAtualizacao": "2024-06-01",
        "poloAtivo": [{"nome": "MPF"}],
        "poloPassivo": [{"nome": "FULANO"}],
    }
]

_HTML_RESULT = """
<html>
<table>
<tr>
<td>1234567-89.2024.8.21.0001</td>
<td>classe: Execução Fiscal</td>
<td>vara: 2ª Vara da Fazenda</td>
<td>data de ajuizamento: 10/05/2024</td>
</tr>
</table>
</html>
"""


class TestEprocChannel:
    def setup_method(self) -> None:
        self.channel = EprocChannel()

    def test_channel_name(self) -> None:
        assert self.channel.channel_name == FonteOrigem.EPROC

    def test_supported_tribunais(self) -> None:
        tribunais = self.channel.supported_tribunais()
        assert "trf4" in tribunais
        assert "tjrs" in tribunais
        assert "tjsc" in tribunais
        assert "tjto" in tribunais

    @pytest.mark.asyncio
    async def test_trf4_json_search_by_name(self) -> None:
        import json

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _TRF4_JSON

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.eproc.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("trf4", "FULANO")

        assert len(results) == 1
        assert results[0].fonte == FonteOrigem.EPROC
        assert results[0].classe == "Ação Civil Pública"

    @pytest.mark.asyncio
    async def test_trf4_json_search_by_cpf(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _TRF4_JSON

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.eproc.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_cpf("trf4", "123.456.789-00")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_html_search(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = _HTML_RESULT

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.eproc.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjrs", "FULANO")

        assert len(results) == 1
        assert results[0].numero_cnj == "1234567-89.2024.8.21.0001"

    @pytest.mark.asyncio
    async def test_oab_search_returns_empty(self) -> None:
        results = await self.channel.search_by_oab("trf4", "SP123456")
        assert results == []

    @pytest.mark.asyncio
    async def test_unsupported_tribunal(self) -> None:
        results = await self.channel.search_by_name("stj", "FULANO")
        assert results == []

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.eproc.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("trf4", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self) -> None:
        with patch("juris.busca.channels.eproc.busca_circuit_breaker") as mock_cb:
            mock_cb.check.side_effect = RuntimeError("Circuit open")
            results = await self.channel.search_by_name("trf4", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_polo_extraction(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _TRF4_JSON

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.eproc.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("trf4", "FULANO")

        assert results[0].polo_ativo == ["MPF"]
        assert results[0].polo_passivo == ["FULANO"]

    @pytest.mark.asyncio
    async def test_empty_json_response(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.eproc.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("trf4", "NINGUEM")

        assert results == []
