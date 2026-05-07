"""Tests for intimacoes operations."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from juris.mni.operations.intimacoes import (
    AvisosResult,
    consultar_avisos_pendentes,
    consultar_teor_comunicacao,
    confirmar_recebimento,
)
from tests.fixtures.mni_avisos_response import (
    make_avisos_response,
    make_avisos_response_empty,
    make_avisos_response_error,
    make_teor_response,
    make_teor_response_error,
)


class TestConsultarAvisosPendentes:
    def _mock_client(self, response) -> MagicMock:
        client = MagicMock()
        client.service.consultarAvisosPendentes.return_value = response
        return client

    def test_returns_avisos(self) -> None:
        client = self._mock_client(make_avisos_response())
        result = consultar_avisos_pendentes(client, "07671039632", "07671039632")

        assert result.sucesso is True
        assert len(result.avisos) == 2
        assert result.avisos[0].id_aviso == "AV001"
        assert result.avisos[0].tipo_comunicacao == "intimacao"
        assert result.avisos[1].tipo_comunicacao == "citacao"

    def test_empty_avisos(self) -> None:
        client = self._mock_client(make_avisos_response_empty())
        result = consultar_avisos_pendentes(client, "07671039632", "07671039632")

        assert result.sucesso is True
        assert len(result.avisos) == 0

    def test_auth_error(self) -> None:
        client = self._mock_client(make_avisos_response_error())
        result = consultar_avisos_pendentes(client, "00000000000", "wrong")

        assert result.sucesso is False
        assert "autenticação" in result.mensagem.lower()

    def test_aviso_has_dates(self) -> None:
        client = self._mock_client(make_avisos_response())
        result = consultar_avisos_pendentes(client, "07671039632", "07671039632")

        aviso = result.avisos[0]
        assert aviso.data_disponibilizacao == datetime(2026, 4, 28, 10, 0)
        assert aviso.data_limite_ciencia == datetime(2026, 5, 5, 23, 59)


class TestConsultarTeorComunicacao:
    def test_returns_content(self) -> None:
        client = MagicMock()
        client.service.consultarTeorComunicacao.return_value = make_teor_response()

        teor = consultar_teor_comunicacao(client, "07671039632", "07671039632", "AV001")

        assert teor is not None
        assert "intimado" in teor
        assert "15 dias" in teor

    def test_returns_none_on_error(self) -> None:
        client = MagicMock()
        client.service.consultarTeorComunicacao.return_value = make_teor_response_error()

        teor = consultar_teor_comunicacao(client, "07671039632", "07671039632", "AV999")
        assert teor is None


class TestConfirmarRecebimento:
    def test_success(self) -> None:
        client = MagicMock()
        client.service.confirmarRecebimento.return_value = MagicMock(sucesso=True, mensagem="")

        result = confirmar_recebimento(client, "07671039632", "07671039632", "AV001")
        assert result is True

    def test_failure(self) -> None:
        client = MagicMock()
        client.service.confirmarRecebimento.return_value = MagicMock(sucesso=False, mensagem="Erro")

        result = confirmar_recebimento(client, "07671039632", "07671039632", "AV001")
        assert result is False
