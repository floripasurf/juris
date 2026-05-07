"""Tests for juris.busca.channels.projudi."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from juris.busca.channels.projudi import ProjudiChannel
from juris.busca.models import FonteOrigem

_PROJUDI_HTML = """
<html>
<table>
<tr><th>Processo</th><th>Classe</th><th>Data</th><th>Vara</th></tr>
<tr>
  <td>1234567-89.2024.8.16.0001</td>
  <td>Ação Penal</td>
  <td>10/02/2024</td>
  <td>1ª Vara Criminal</td>
</tr>
</table>
</html>
"""


class TestProjudiChannel:
    def setup_method(self) -> None:
        self.channel = ProjudiChannel()

    def test_channel_name(self) -> None:
        assert self.channel.channel_name == FonteOrigem.PROJUDI

    def test_supported_tribunais(self) -> None:
        assert self.channel.supported_tribunais() == ["tjpr"]

    @pytest.mark.asyncio
    async def test_search_by_name(self) -> None:
        mock_session_resp = MagicMock()
        mock_session_resp.status_code = 200
        mock_session_resp.raise_for_status = MagicMock()

        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.raise_for_status = MagicMock()
        mock_search_resp.text = _PROJUDI_HTML

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_session_resp)
        mock_client.post = AsyncMock(return_value=mock_search_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.projudi.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjpr", "FULANO")

        assert len(results) == 1
        assert results[0].numero_cnj == "1234567-89.2024.8.16.0001"
        assert results[0].fonte == FonteOrigem.PROJUDI
        assert results[0].tribunal == "TJPR"

    @pytest.mark.asyncio
    async def test_search_by_cpf(self) -> None:
        mock_session_resp = MagicMock()
        mock_session_resp.status_code = 200
        mock_session_resp.raise_for_status = MagicMock()

        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.raise_for_status = MagicMock()
        mock_search_resp.text = _PROJUDI_HTML

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_session_resp)
        mock_client.post = AsyncMock(return_value=mock_search_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.projudi.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_cpf("tjpr", "123.456.789-00")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_oab_returns_empty(self) -> None:
        results = await self.channel.search_by_oab("tjpr", "PR123456")
        assert results == []

    @pytest.mark.asyncio
    async def test_wrong_tribunal(self) -> None:
        results = await self.channel.search_by_name("tjsp", "FULANO")
        assert results == []

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.projudi.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjpr", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self) -> None:
        with patch("juris.busca.channels.projudi.busca_circuit_breaker") as mock_cb:
            mock_cb.check.side_effect = RuntimeError("Circuit open")
            results = await self.channel.search_by_name("tjpr", "FULANO")

        assert results == []

    @pytest.mark.asyncio
    async def test_empty_html(self) -> None:
        mock_session_resp = MagicMock()
        mock_session_resp.status_code = 200
        mock_session_resp.raise_for_status = MagicMock()

        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.raise_for_status = MagicMock()
        mock_search_resp.text = "<html></html>"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_session_resp)
        mock_client.post = AsyncMock(return_value=mock_search_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("juris.busca.channels.projudi.httpx.AsyncClient", return_value=mock_client):
            results = await self.channel.search_by_name("tjpr", "NINGUEM")

        assert results == []
