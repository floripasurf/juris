"""The mTLS CLI commands must read through the MNIReadService boundary (ADR-0015)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from juris.cli.main import app
from juris.mni.operations.intimacoes import Aviso, AvisosResult
from juris.mni.parsers.processo import Movimento, ProcessoDomain

runner = CliRunner()
_CNJ = "5082351-40.2017.8.13.0024"


def _processo() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj=_CNJ,
        tribunal="tjmg",
        classe="Procedimento Comum Cível",
        movimentos=[Movimento(data_hora=datetime(2018, 11, 7, 0, 31), tipo="nacional", codigo_nacional=1051)],
    )


# (material, resolved_senha, resolved_pin) — what the migrated _mtls_session returns.
_FAKE_SESSION = (MagicMock(subject="CN=X", not_valid_after="2027-06-04", cpf="07671039632"), "senha", "1234")


def test_consulta_mtls_reads_via_service() -> None:
    with (
        patch("juris.cli.main._mtls_session", return_value=_FAKE_SESSION),
        patch(
            "juris.mni.service.InProcessMNIReadService.consultar_processo",
            return_value=_processo(),
        ) as mock_read,
    ):
        result = runner.invoke(
            app,
            ["consulta", _CNJ, "--tribunal", "tjmg", "--cpf", "07671039632", "--pin", "1234"],
        )

    assert result.exit_code == 0, result.output
    mock_read.assert_called_once()
    assert _CNJ in result.output


def test_avisos_reads_via_service() -> None:
    avisos = AvisosResult(
        sucesso=True,
        mensagem="ok",
        avisos=[Aviso(id_aviso="1", tipo_comunicacao="intimacao", numero_processo=_CNJ)],
    )
    with (
        patch("juris.cli.main._mtls_session", return_value=_FAKE_SESSION),
        patch(
            "juris.mni.service.InProcessMNIReadService.consultar_avisos",
            return_value=avisos,
        ) as mock_avisos,
    ):
        result = runner.invoke(
            app,
            ["avisos", "--tribunal", "tjmg", "--cpf", "07671039632", "--pin", "1234"],
        )

    assert result.exit_code == 0, result.output
    mock_avisos.assert_called_once()
    assert _CNJ in result.output
