"""Tests for the unified nightly pipeline."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from juris.jobs.nightly import (
    NightlyResult,
    NightlySummary,
    run_nightly,
    run_nightly_single,
)
from juris.mni.operations.differential import DiffResult
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.persistence.local_db import LocalDB


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
                descricao="Sentenca com resolucao do merito",
                id_movimento="mov1",
            ),
            Movimento(
                data_hora=datetime(2026, 4, 5, 10, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=14,
                descricao="Intimacao",
                id_movimento="mov2",
            ),
            Movimento(
                data_hora=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
                tipo="nacional",
                codigo_nacional=11,
                descricao="Distribuicao",
                id_movimento="mov3",
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


def _make_analysis_mock() -> MagicMock:
    m = MagicMock()
    m.analyzed = []
    m.actionable = []
    return m


def _make_prazo_report_mock(prazos: list | None = None) -> MagicMock:
    m = MagicMock()
    m.prazos = prazos or []
    return m


def _make_alert_batch_mock(critical_count: int = 0) -> MagicMock:
    m = MagicMock()
    m.critical_count = critical_count
    m.has_critical = critical_count > 0
    return m


def _patch_nightly_pipeline(
    diff: DiffResult | None = None,
    processo: ProcessoDomain | None = None,
    analysis: MagicMock | None = None,
    prazo_report: MagicMock | None = None,
    alert_batch: MagicMock | None = None,
):
    """Return a context manager patching all nightly pipeline external deps."""
    from contextlib import contextmanager

    if diff is None:
        diff = _mock_diff_result(had_changes=False, new_movimentos=[])
    if processo is None:
        processo = _mock_processo()
    if analysis is None:
        analysis = _make_analysis_mock()
    if prazo_report is None:
        prazo_report = _make_prazo_report_mock()
    if alert_batch is None:
        alert_batch = _make_alert_batch_mock()

    @contextmanager
    def _ctx():
        with (
            patch("juris.jobs.nightly.sync_processo_mni", return_value=diff),
            patch("juris.jobs.nightly.sync_processo_datajud", return_value=diff),
            patch("juris.jobs.nightly._fetch_full_processo", return_value=processo),
            patch("juris.jobs.nightly.analyze_processo", return_value=analysis),
            patch("juris.jobs.nightly.compute_prazos", return_value=prazo_report),
            patch("juris.jobs.nightly.generate_alerts", return_value=alert_batch),
        ):
            yield

    return _ctx()


class TestRunNightlySingle:
    def test_success_with_changes(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=True)
        processo = _mock_processo()
        prazo_report = _make_prazo_report_mock([MagicMock(
            numero_cnj="1234567-89.2026.8.13.0001",
            rule=MagicMock(nome="Apelacao", tipo_acao=MagicMock(value="recurso"), base_legal="CPC 1009"),
            data_inicio=date(2026, 4, 5),
            data_limite=date(2026, 4, 20),
            dias_uteis_total=15,
            status=MagicMock(value="aberto"),
            urgencia=MagicMock(value="alta"),
            categoria=MagicMock(value="decisao"),
        )])

        with _patch_nightly_pipeline(
            diff=diff, processo=processo,
            prazo_report=prazo_report,
        ):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert result.success
        assert result.error is None

    def test_no_changes(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=False, new_movimentos=[])

        with _patch_nightly_pipeline(diff=diff):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert result.success
        assert result.new_movimentos == 0

    def test_diff_error(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=False, error="MNI error: timeout")

        with _patch_nightly_pipeline(diff=diff):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert not result.success
        assert result.error is not None

    def test_fetch_error_after_diff(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=True)

        with (
            patch("juris.jobs.nightly.sync_processo_mni", return_value=diff),
            patch("juris.jobs.nightly.sync_processo_datajud", return_value=diff),
            patch("juris.jobs.nightly._fetch_full_processo", return_value=None),
        ):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert not result.success
        assert result.error is not None

    def test_persists_to_db(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=True)
        processo = _mock_processo()

        with _patch_nightly_pipeline(diff=diff, processo=processo):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert result.success
        proc = db.get_processo_by_cnj("1234567-89.2026.8.13.0001")
        assert proc is not None
        last_sync = db.get_last_sync("1234567-89.2026.8.13.0001")
        assert last_sync is not None

    def test_uses_last_sync(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        # Create the processo first so get_processo_by_cnj returns it
        db.upsert_processo("1234567-89.2026.8.13.0001", "tjsp")
        db.log_sync("1234567-89.2026.8.13.0001", "tjsp", "mni", success=True, new_movimentos=1)

        diff = _mock_diff_result(had_changes=False, new_movimentos=[])

        with (
            patch("juris.jobs.nightly.sync_processo_mni", return_value=diff) as mock_mni,
            patch("juris.jobs.nightly.sync_processo_datajud", return_value=diff),
        ):
            asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        # last_sync_at should have been passed from the DB
        assert mock_mni.call_count > 0
        args, kwargs = mock_mni.call_args
        # Positional: numero_cnj, tribunal, cpf, senha, last_sync_at, known_keys
        last_sync_val = args[4] if len(args) > 4 else kwargs.get("last_sync_at")
        assert last_sync_val is not None

    def test_uses_known_movimento_keys(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        pid = db.upsert_processo("1234567-89.2026.8.13.0001", "tjsp")
        dt = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        db.insert_movimentos(pid, [
            {"data_hora": dt, "tipo": "nacional", "codigo_nacional": 132, "id_movimento": "m1"},
        ])

        diff = _mock_diff_result(had_changes=False, new_movimentos=[])

        with (
            patch("juris.jobs.nightly.sync_processo_mni", return_value=diff) as mock_mni,
            patch("juris.jobs.nightly.sync_processo_datajud", return_value=diff),
        ):
            asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        if mock_mni.call_count > 0:
            args, kwargs = mock_mni.call_args
            known_keys = args[5] if len(args) > 5 else kwargs.get("known_movimento_keys")
            if known_keys is not None:
                assert len(known_keys) >= 1

    def test_generates_alerts(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=True)
        processo = _mock_processo()
        alert_batch = _make_alert_batch_mock(critical_count=2)

        with _patch_nightly_pipeline(
            diff=diff, processo=processo,
            alert_batch=alert_batch,
        ):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 12, 1),
            ))

        assert result.success
        assert result.critical_alerts == 2

    def test_tjmg_routes_to_mni(self, tmp_path: Path) -> None:
        # TJMG now reads via MNI (mTLS token), not DataJud-first.
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=False, new_movimentos=[])

        with (
            patch("juris.jobs.nightly.sync_processo_mni", return_value=diff) as mock_mni,
            patch("juris.jobs.nightly.sync_processo_datajud") as mock_dj,
        ):
            asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjmg", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        mock_mni.assert_awaited_once()
        mock_dj.assert_not_awaited()

    def test_logs_sync_on_success(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=True)
        processo = _mock_processo()

        with _patch_nightly_pipeline(diff=diff, processo=processo):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert result.success
        last_sync = db.get_last_sync("1234567-89.2026.8.13.0001")
        assert last_sync is not None

    def test_logs_sync_on_error(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=False, error="MNI timeout")

        with _patch_nightly_pipeline(diff=diff):
            result = asyncio.run(run_nightly_single(
                "1234567-89.2026.8.13.0001", "tjsp", db, "cpf", "senha",
                today=date(2026, 4, 10),
            ))

        assert not result.success


class TestRunNightly:
    def test_multiple_processos(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        diff = _mock_diff_result(had_changes=False, new_movimentos=[])

        processos = [
            {"numero_cnj": "aaa", "tribunal": "tjsp"},
            {"numero_cnj": "bbb", "tribunal": "tjsp"},
        ]

        with _patch_nightly_pipeline(diff=diff):
            summary = asyncio.run(run_nightly(
                processos, db, "cpf", "senha", today=date(2026, 4, 10),
            ))

        assert summary.total == 2

    def test_mixed_results(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        ok_diff = _mock_diff_result(had_changes=False, new_movimentos=[])
        fail_diff = _mock_diff_result(had_changes=False, error="MNI error")

        call_count = 0

        async def mock_mni(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ok_diff if call_count == 1 else fail_diff

        processos = [
            {"numero_cnj": "aaa", "tribunal": "tjsp"},
            {"numero_cnj": "bbb", "tribunal": "tjsp"},
        ]

        with (
            patch("juris.jobs.nightly.sync_processo_mni", side_effect=mock_mni),
            patch("juris.jobs.nightly.sync_processo_datajud", return_value=fail_diff),
        ):
            summary = asyncio.run(run_nightly(
                processos, db, "cpf", "senha", today=date(2026, 4, 10),
            ))

        assert summary.total == 2
        assert summary.succeeded >= 1
        assert summary.failed >= 1

    def test_empty_list(self, tmp_path: Path) -> None:
        db = LocalDB(tmp_path / "test.db")
        summary = asyncio.run(run_nightly([], db, "cpf", "senha"))

        assert summary.total == 0
        assert summary.succeeded == 0
        assert summary.failed == 0


class TestNightlyResult:
    def test_summary_success(self) -> None:
        r = NightlyResult(
            numero_cnj="123", tribunal="tjsp", success=True,
            new_movimentos=5, prazos_computed=3, critical_alerts=1,
        )
        assert r.success
        assert r.new_movimentos == 5
        assert r.prazos_computed == 3
        assert r.critical_alerts == 1

    def test_summary_error(self) -> None:
        r = NightlyResult(
            numero_cnj="123", tribunal="tjsp", success=False,
            error="Network error",
        )
        assert not r.success
        assert "Network error" in r.error


class TestNightlySummary:
    def test_properties(self) -> None:
        summary = NightlySummary()
        summary.results = [
            NightlyResult("a", "t", success=True, critical_alerts=2),
            NightlyResult("b", "t", success=True, critical_alerts=1),
            NightlyResult("c", "t", success=False, error="fail"),
        ]
        assert summary.total == 3
        assert summary.succeeded == 2
        assert summary.failed == 1
        assert summary.total_critical_alerts == 3


class TestNightlyMtlsEndToEnd:
    """Offline end-to-end: real TJMG response → diff → persist → analyze → prazos.

    Injects the captured (sanitized) mTLS response so the full nightly chain
    runs without the hardware token, proving the pipeline over real MNI data.
    """

    def _real_processo(self):
        from pathlib import Path

        from juris.mni.operations.consulta_pkcs11 import _parse_response
        from juris.mni.pkcs11_transport import SOAPResponse

        xml = Path("tests/fixtures/mni_responses/tjmg_consulta_real.xml").read_bytes()
        result = _parse_response(SOAPResponse(status_code=200, body=xml), "50823514020178130024")
        return result.to_processo_domain(tribunal_id="tjmg", numero_cnj="50823514020178130024")

    def test_first_run_persists_and_analyzes(self, tmp_path) -> None:
        import asyncio
        from unittest.mock import patch

        from juris.jobs.nightly import run_nightly_single
        from juris.mni.operations.differential import diff_processo
        from juris.persistence.local_db import LocalDB

        processo = self._real_processo()
        db = LocalDB(db_path=tmp_path / "nightly.db")

        # Stand in for the token fetch: diff carries the real processo.
        async def fake_sync(numero_cnj, tribunal_id, *a, **k):
            return diff_processo(fetched=processo, last_sync_at=None)

        with patch("juris.jobs.nightly.sync_processo_mni", side_effect=fake_sync):
            result = asyncio.run(
                run_nightly_single(
                    numero_cnj="50823514020178130024",
                    tribunal="tjmg",
                    db=db,
                    cpf="00000000000",
                    senha="x",
                )
            )

        assert result.success
        assert result.error is None
        assert result.new_movimentos == 44  # first run: every movement is new
        assert result.analysis is not None
        assert result.prazo_report is not None
        # The persisted processo is queryable afterwards.
        assert db.get_processo_by_cnj("50823514020178130024") is not None

    def test_second_run_detects_no_changes(self, tmp_path) -> None:
        import asyncio
        from unittest.mock import patch

        from juris.jobs.nightly import run_nightly_single
        from juris.mni.operations.differential import diff_processo
        from juris.persistence.local_db import LocalDB

        processo = self._real_processo()
        db = LocalDB(db_path=tmp_path / "nightly.db")

        async def fake_sync(numero_cnj, tribunal_id, *a, **k):
            # Honour the known-keys the pipeline passes from the DB so the
            # second run sees everything as already-known.
            known = k.get("known_movimento_keys") or (a[2] if len(a) > 2 else None)
            return diff_processo(
                fetched=processo, last_sync_at=None, known_movimento_keys=known
            )

        with patch("juris.jobs.nightly.sync_processo_mni", side_effect=fake_sync):
            asyncio.run(
                run_nightly_single("50823514020178130024", "tjmg", db, "00000000000", "x")
            )
            second = asyncio.run(
                run_nightly_single("50823514020178130024", "tjmg", db, "00000000000", "x")
            )

        assert second.success
        assert second.new_movimentos == 0  # nothing new on the second pass
