"""Tests for the overnight differential sync job."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.jobs.overnight import (
    SyncSummary,
    run_overnight_sync,
    sync_processo_datajud,
    sync_processo_mni,
)
from juris.mni.operations.differential import DiffResult
from juris.mni.parsers.processo import Movimento, ProcessoDomain


def _mock_processo() -> ProcessoDomain:
    """Create a mock ProcessoDomain for testing."""
    return ProcessoDomain(
        numero_cnj="1234567-89.2026.8.13.0001",
        tribunal="tjsp",
        classe="Procedimento Comum Civel",
        assunto="Danos Morais",
        movimentos=[
            Movimento(
                data_hora=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=132,
                descricao="Sentenca",
                id_movimento="mov1",
            ),
        ],
    )


def _mock_diff_result(
    *,
    had_changes: bool = True,
    new_movimentos: list[Movimento] | None = None,
    error: str | None = None,
) -> DiffResult:
    """Create a mock DiffResult for testing."""
    if new_movimentos is None and had_changes:
        new_movimentos = [
            Movimento(
                data_hora=datetime(2026, 4, 10, 10, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=14,
                descricao="Intimacao",
                id_movimento="mov_new",
            ),
        ]
    return DiffResult(
        numero_cnj="1234567-89.2026.8.13.0001",
        tribunal_id="tjsp",
        new_movimentos=new_movimentos or [],
        had_changes=had_changes,
        error=error,
    )


class TestSyncProcessoMni:
    def test_success(self) -> None:
        mock_response = MagicMock(sucesso=True)
        processo = _mock_processo()

        with (
            patch("juris.jobs.overnight.circuit_breaker") as mock_cb,
            patch("juris.mni.auth.PasswordAuth"),
            patch("juris.mni.client.get_mni_client"),
            patch("juris.mni.operations.consulta.consultar_processo", return_value=mock_response),
            patch("juris.jobs.overnight.parse_processo", return_value=processo),
            patch("juris.jobs.overnight.diff_processo", return_value=_mock_diff_result()),
        ):
            mock_cb.check.return_value = None
            result = asyncio.run(sync_processo_mni(
                "1234567-89.2026.8.13.0001", "tjsp", "cpf", "senha",
            ))

        assert result.had_changes
        assert result.error is None
        mock_cb.record_success.assert_called_once_with("tjsp")

    def test_circuit_open(self) -> None:
        with patch("juris.jobs.overnight.circuit_breaker") as mock_cb:
            mock_cb.check.side_effect = RuntimeError("Circuit open for tribunal 'tjsp'")
            result = asyncio.run(sync_processo_mni(
                "1234567-89.2026.8.13.0001", "tjsp", "cpf", "senha",
            ))

        assert result.error is not None
        assert "Circuit open" in result.error

    def test_mni_error_response(self) -> None:
        mock_response = MagicMock(sucesso=False, mensagem="Processo nao encontrado")

        with (
            patch("juris.jobs.overnight.circuit_breaker") as mock_cb,
            patch("juris.mni.auth.PasswordAuth"),
            patch("juris.mni.client.get_mni_client"),
            patch("juris.mni.operations.consulta.consultar_processo", return_value=mock_response),
        ):
            mock_cb.check.return_value = None
            result = asyncio.run(sync_processo_mni(
                "1234567-89.2026.8.13.0001", "tjsp", "cpf", "senha",
            ))

        assert result.error is not None
        assert "MNI error" in result.error
        mock_cb.record_failure.assert_called_once_with("tjsp")

    def test_exception(self) -> None:
        with (
            patch("juris.jobs.overnight.circuit_breaker") as mock_cb,
            patch("juris.mni.auth.PasswordAuth"),
            patch("juris.mni.client.get_mni_client"),
            patch("juris.mni.operations.consulta.consultar_processo", side_effect=ConnectionError("timeout")),
        ):
            mock_cb.check.return_value = None
            result = asyncio.run(sync_processo_mni(
                "1234567-89.2026.8.13.0001", "tjsp", "cpf", "senha",
            ))

        assert result.error is not None
        assert "ConnectionError" in result.error
        mock_cb.record_failure.assert_called_once_with("tjsp")


class TestSyncProcessoDatajud:
    def test_success(self) -> None:
        processo = _mock_processo()

        with (
            patch("juris.datajud.client.consultar_processo", return_value={"raw": "data"}),
            patch("juris.datajud.parser.parse_datajud_processo", return_value=processo),
            patch("juris.jobs.overnight.diff_processo", return_value=_mock_diff_result()),
        ):
            result = asyncio.run(sync_processo_datajud(
                "1234567-89.2026.8.13.0001", "tjmg",
            ))

        assert result.had_changes
        assert result.error is None

    def test_not_found(self) -> None:
        with patch("juris.datajud.client.consultar_processo", return_value=None):
            result = asyncio.run(sync_processo_datajud(
                "0000000-00.0000.0.00.0000", "tjmg",
            ))

        assert result.error is not None
        assert "Not found" in result.error

    def test_exception(self) -> None:
        with patch("juris.datajud.client.consultar_processo", side_effect=Exception("API down")):
            result = asyncio.run(sync_processo_datajud(
                "1234567-89.2026.8.13.0001", "tjmg",
            ))

        assert result.error is not None
        assert "DataJud" in result.error


class TestRunOvernightSync:
    def test_basic_sync(self) -> None:
        diff = _mock_diff_result(had_changes=True)

        processos = [
            {"numero_cnj": "1234567-89.2026.8.13.0001", "tribunal_id": "tjsp"},
        ]

        with patch("juris.jobs.overnight.sync_processo_mni", return_value=diff) as mock_mni:
            summary = asyncio.run(run_overnight_sync(processos, cpf="cpf", senha="senha"))

        assert summary.processos_checked == 1
        assert summary.processos_updated == 1
        assert summary.processos_failed == 0
        mock_mni.assert_awaited_once()

    def test_datajud_fallback_tribunal(self) -> None:
        diff = _mock_diff_result(had_changes=True)

        processos = [
            {"numero_cnj": "1234567-89.2026.8.13.0001", "tribunal_id": "tjmg"},
        ]

        with (
            patch("juris.jobs.overnight.sync_processo_mni") as mock_mni,
            patch("juris.jobs.overnight.sync_processo_datajud", return_value=diff) as mock_dj,
        ):
            summary = asyncio.run(run_overnight_sync(processos, cpf="cpf", senha="senha"))

        mock_mni.assert_not_awaited()
        mock_dj.assert_awaited_once()
        assert summary.processos_updated == 1

    def test_mni_fail_datajud_fallback(self) -> None:
        mni_fail = _mock_diff_result(had_changes=False, error="MNI error: timeout")
        dj_ok = _mock_diff_result(had_changes=True)

        processos = [
            {"numero_cnj": "1234567-89.2026.8.13.0001", "tribunal_id": "tjsp"},
        ]

        with (
            patch("juris.jobs.overnight.sync_processo_mni", return_value=mni_fail),
            patch("juris.jobs.overnight.sync_processo_datajud", return_value=dj_ok),
        ):
            summary = asyncio.run(run_overnight_sync(processos, cpf="cpf", senha="senha"))

        assert summary.processos_updated == 1
        assert summary.processos_failed == 0

    def test_empty_processos(self) -> None:
        summary = asyncio.run(run_overnight_sync([], cpf="cpf", senha="senha"))

        assert summary.processos_checked == 0
        assert summary.processos_updated == 0
        assert summary.processos_failed == 0

    def test_summary_counts(self) -> None:
        ok_diff = _mock_diff_result(had_changes=True)
        fail_diff = _mock_diff_result(had_changes=False, error="MNI error: down")

        processos = [
            {"numero_cnj": "aaa", "tribunal_id": "tjsp"},
            {"numero_cnj": "bbb", "tribunal_id": "tjsp"},
            {"numero_cnj": "ccc", "tribunal_id": "tjsp"},
        ]

        call_count = 0

        async def mock_mni(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return ok_diff
            return fail_diff

        async def mock_dj_fail(*args, **kwargs):
            return fail_diff

        with (
            patch("juris.jobs.overnight.sync_processo_mni", side_effect=mock_mni),
            patch("juris.jobs.overnight.sync_processo_datajud", side_effect=mock_dj_fail),
        ):
            summary = asyncio.run(run_overnight_sync(processos, cpf="cpf", senha="senha"))

        assert summary.processos_checked == 3
        assert summary.processos_updated == 2
        assert summary.processos_failed == 1


class TestSyncSummary:
    def test_duration(self) -> None:
        s = SyncSummary(
            started_at=datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 4, 1, 0, 1, 30, tzinfo=UTC),
        )
        assert s.duration_seconds == 90.0

    def test_duration_not_finished(self) -> None:
        s = SyncSummary()
        assert s.duration_seconds == 0

    def test_finish(self) -> None:
        s = SyncSummary()
        assert s.finished_at is None
        s.finish()
        assert s.finished_at is not None
        assert s.duration_seconds > 0
