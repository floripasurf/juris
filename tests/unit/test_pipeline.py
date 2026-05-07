"""Tests for the full sync pipeline."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from juris.jobs.pipeline import PipelineResult, PipelineSummary, run_pipeline, run_pipeline_single
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.persistence.local_db import LocalDB


def _mock_processo() -> ProcessoDomain:
    """Create a mock ProcessoDomain for testing."""
    from datetime import UTC, datetime
    return ProcessoDomain(
        numero_cnj="1234567-89.2026.8.13.0001",
        tribunal="tjmg",
        classe="Procedimento Comum Cível",
        assunto="Danos Morais",
        movimentos=[
            Movimento(
                data_hora=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=132,
                descricao="Sentença com resolução do mérito",
                id_movimento="mov1",
            ),
            Movimento(
                data_hora=datetime(2026, 4, 5, 10, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=14,
                descricao="Intimação",
                id_movimento="mov2",
            ),
            Movimento(
                data_hora=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=11,
                descricao="Distribuição",
                id_movimento="mov3",
            ),
        ],
    )


class TestRunPipelineSingle:
    def test_success(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        processo = _mock_processo()

        with patch("juris.jobs.pipeline._fetch_processo", return_value=processo):
            result = asyncio.run(run_pipeline_single(
                "1234567-89.2026.8.13.0001", "tjmg", db, today=date(2026, 4, 10),
            ))

        assert result.success
        assert result.error is None
        assert result.total_movimentos == 3
        assert result.new_movimentos == 3
        assert result.prazos_computed > 0
        assert result.analysis is not None
        assert result.prazo_report is not None

    def test_persists_to_db(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        processo = _mock_processo()

        with patch("juris.jobs.pipeline._fetch_processo", return_value=processo):
            asyncio.run(run_pipeline_single(
                "1234567-89.2026.8.13.0001", "tjmg", db, today=date(2026, 4, 10),
            ))

        # Check DB state
        proc = db.get_processo_by_cnj("1234567-89.2026.8.13.0001")
        assert proc is not None
        assert proc.classe == "Procedimento Comum Cível"

        prazos = db.get_all_prazos("1234567-89.2026.8.13.0001")
        assert len(prazos) > 0

        last_sync = db.get_last_sync("1234567-89.2026.8.13.0001")
        assert last_sync is not None

    def test_dedup_on_second_run(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        processo = _mock_processo()

        with patch("juris.jobs.pipeline._fetch_processo", return_value=processo):
            r1 = asyncio.run(run_pipeline_single(
                "1234567-89.2026.8.13.0001", "tjmg", db, today=date(2026, 4, 10),
            ))
            r2 = asyncio.run(run_pipeline_single(
                "1234567-89.2026.8.13.0001", "tjmg", db, today=date(2026, 4, 10),
            ))

        assert r1.new_movimentos == 3
        assert r2.new_movimentos == 0  # All deduped

    def test_not_found(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")

        with patch("juris.jobs.pipeline._fetch_processo", return_value=None):
            result = asyncio.run(run_pipeline_single(
                "0000000-00.0000.0.00.0000", "tjmg", db,
            ))

        assert not result.success
        assert "Not found" in result.error

    def test_fetch_exception(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")

        with patch("juris.jobs.pipeline._fetch_processo", side_effect=Exception("Network error")):
            result = asyncio.run(run_pipeline_single(
                "0000000-00.0000.0.00.0000", "tjmg", db,
            ))

        assert not result.success
        assert "Network error" in result.error

    def test_generates_alerts(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        processo = _mock_processo()

        # Set today far after movements so prazos are vencidos
        with patch("juris.jobs.pipeline._fetch_processo", return_value=processo):
            result = asyncio.run(run_pipeline_single(
                "1234567-89.2026.8.13.0001", "tjmg", db, today=date(2026, 12, 1),
            ))

        assert result.success
        assert result.critical_alerts > 0
        assert result.alert_batch is not None
        assert result.alert_batch.has_critical


class TestRunPipeline:
    def test_multiple_processos(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        processo = _mock_processo()

        processos = [
            {"numero_cnj": "1234567-89.2026.8.13.0001", "tribunal": "tjmg"},
            {"numero_cnj": "9999999-00.0000.0.00.0000", "tribunal": "tjmg"},
        ]

        def mock_fetch(cnj, tribunal):
            if cnj == "1234567-89.2026.8.13.0001":
                return processo
            return None

        with patch("juris.jobs.pipeline._fetch_processo", side_effect=mock_fetch):
            summary = asyncio.run(run_pipeline(processos, db=db, today=date(2026, 4, 10)))

        assert summary.total == 2
        assert summary.succeeded == 1
        assert summary.failed == 1

    def test_summary_properties(self, tmp_path: Path) -> None:
        summary = PipelineSummary()
        summary.results = [
            PipelineResult("a", "t", success=True, critical_alerts=2),
            PipelineResult("b", "t", success=True, critical_alerts=1),
            PipelineResult("c", "t", success=False, error="fail"),
        ]
        assert summary.total == 3
        assert summary.succeeded == 2
        assert summary.failed == 1
        assert summary.total_critical_alerts == 3


class TestPipelineResult:
    def test_summary_success(self) -> None:
        r = PipelineResult("123", "tjmg", success=True, new_movimentos=5, prazos_computed=3, critical_alerts=1)
        assert "123" in r.summary
        assert "+5 mov" in r.summary
        assert "3 prazos" in r.summary

    def test_summary_error(self) -> None:
        r = PipelineResult("123", "tjmg", error="Network error")
        assert "FAIL" in r.summary
        assert "Network error" in r.summary
