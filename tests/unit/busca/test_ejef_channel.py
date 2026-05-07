"""Tests for juris.busca.channels.ejef."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from juris.busca.channels.ejef import EjefChannel
from juris.busca.models import FonteOrigem

_EJEF_HTML = """
<html>
<table>
<tr><th>Número</th><th>Classe</th><th>Data</th></tr>
<tr>
  <td>1234567-89.2024.8.13.0024</td>
  <td>Ação Cível</td>
  <td>15/03/2024</td>
</tr>
<tr>
  <td>7654321-00.2024.8.13.0024</td>
  <td>Execução Fiscal</td>
  <td>20/04/2024</td>
</tr>
</table>
</html>
"""


class TestEjefChannel:
    def setup_method(self) -> None:
        self.channel = EjefChannel()

    def test_channel_name(self) -> None:
        assert self.channel.channel_name == FonteOrigem.EJEF

    def test_supported_tribunais(self) -> None:
        assert self.channel.supported_tribunais() == ["tjmg"]

    @pytest.mark.asyncio
    async def test_search_by_name(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = _EJEF_HTML

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.ejef.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjmg", "FULANO")

        assert len(results) == 2
        assert results[0].numero_cnj == "1234567-89.2024.8.13.0024"
        assert results[0].fonte == FonteOrigem.EJEF
        assert results[0].tribunal == "TJMG"

    @pytest.mark.asyncio
    async def test_search_by_cpf(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = _EJEF_HTML

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.ejef.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_cpf("tjmg", "123.456.789-00")

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_oab_returns_empty(self) -> None:
        results = await self.channel.search_by_oab("tjmg", "MG123456")
        assert results == []

    @pytest.mark.asyncio
    async def test_wrong_tribunal_returns_empty(self) -> None:
        results = await self.channel.search_by_name("tjsp", "FULANO")
        assert results == []

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.ejef.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjmg", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self) -> None:
        with patch("juris.busca.channels.ejef.busca_circuit_breaker") as mock_cb:
            mock_cb.check.side_effect = RuntimeError("Circuit open")
            results = await self.channel.search_by_name("tjmg", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_empty_html(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "<html><table></table></html>"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.ejef.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjmg", "NINGUEM")

        assert results == []
