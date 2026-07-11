"""Tests for the daily workbench aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from juris.web.processos_service import PrazoView, ProcessoView
from juris.web.workbench_service import build_workbench


def test_workbench_reads_persistent_manifests(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    (case_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "finished_at": "2026-06-30T12:00:00",
                "succeeded": True,
                "degraded": False,
                "output_mode": "rascunho-pesquisa",
                "request": {
                    "numero_cnj": "0001234-56.2026.8.13.0001",
                    "tribunal": "tjmg",
                    "source": "mni",
                },
                "draft": {
                    "grounding_status": "blocked",
                    "grounding_blocked_reason": "citacoes_sem_fonte",
                },
                "reviewer": {
                    "critical_count": 1,
                    "important_count": 2,
                    "suggestion_count": 3,
                },
                "artifacts": [
                    {"name": "rascunho-pesquisa.md", "sha256": "a"},
                    {"name": "run-manifest.json", "sha256": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )

    workbench = build_workbench(processos=[], prazos=[], out_root=tmp_path)

    assert workbench["blocked_cases"][0]["numero_cnj"] == "0001234-56.2026.8.13.0001"
    assert workbench["blocked_cases"][0]["grounding_blocked_reason"] == "citacoes_sem_fonte"
    assert workbench["recent_artifacts"][0]["artifact_count"] == 2
    assert workbench["recent_artifacts"][0]["output_dir"] == "CASE-1"
    assert str(tmp_path) not in json.dumps(workbench)
    assert workbench["recent_artifacts"][0]["review"]["critical"] == 1


def test_workbench_ignores_manifest_symlink_escape(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-manifest.json"
    outside.write_text(
        json.dumps({"request": {"numero_cnj": "ESCAPE"}, "artifacts": []}),
        encoding="utf-8",
    )
    try:
        (case_dir / "run-manifest.json").symlink_to(outside)

        workbench = build_workbench(processos=[], prazos=[], out_root=tmp_path)

        assert workbench["recent_artifacts"] == []
    finally:
        outside.unlink(missing_ok=True)


def test_workbench_builds_daily_process_queues(tmp_path) -> None:
    case_dir = tmp_path / "CASE-A"
    case_dir.mkdir()
    (case_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "finished_at": "2026-06-30T13:00:00",
                "request": {"numero_cnj": "A", "tribunal": "tjmg", "source": "mni"},
                "draft": {"grounding_status": "verified", "grounding_blocked_reason": None},
                "reviewer": {"critical_count": 0, "important_count": 1, "suggestion_count": 0},
                "artifacts": [{"name": "draft.md", "sha256": "a"}],
            }
        ),
        encoding="utf-8",
    )
    synced = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
    prazo = datetime(2026, 7, 1, 18, 0, tzinfo=UTC)
    processos = [
        ProcessoView(
            numero_cnj="A",
            tribunal="tjmg",
            classe="Contestação",
            assunto="Cobrança",
            last_sync_at=synced,
            prazos_pendentes=2,
            proximo_prazo=prazo,
            proximo_prazo_urgencia="alta",
        )
    ]
    prazos = [
        PrazoView(
            numero_cnj="A",
            data_limite=prazo,
            urgencia="alta",
            status="aberto",
            rule_nome="Contestação",
            tipo_acao="contestar",
        )
    ]

    workbench = build_workbench(processos=processos, prazos=prazos, out_root=tmp_path)

    assert workbench["critical_deadlines"][0]["numero_cnj"] == "A"
    assert workbench["critical_deadlines"][0]["latest_run"]["source"] == "mni"
    assert workbench["recent_movements"][0]["last_sync_at"] == synced.isoformat()
    assert workbench["recent_movements"][0]["latest_run"]["grounding_status"] == "verified"
    assert workbench["draft_ready"][0]["prazos_pendentes"] == 2
    assert workbench["draft_ready"][0]["latest_run"]["review"]["important"] == 1


def test_workbench_includes_pending_filings(tmp_path) -> None:
    from juris.web.workbench_service import build_workbench

    # a pending filing under the tenant's filing root
    pending = tmp_path / "filings" / "5082351-40.2017.8.13.0024" / "20260701_pending"
    pending.mkdir(parents=True)

    wb = build_workbench(processos=[], prazos=[], out_root=tmp_path, filing_root=tmp_path / "filings")
    assert "pending_filings" in wb
    assert any(p["receipt_id"] == "20260701_pending" for p in wb["pending_filings"])


def test_workbench_includes_nightly_sync_status(tmp_path) -> None:
    sync_status = {
        "last_run": {"numero_cnj": "A", "success": False, "error": "timeout"},
        "last_success_at": None,
        "last_failure_at": "2026-07-01T02:00:00+00:00",
        "total_runs": 1,
        "successful_runs": 0,
        "failed_runs": 1,
        "recent_failures": [{"numero_cnj": "A", "success": False, "error": "timeout"}],
        "recent_runs": [{"numero_cnj": "A", "success": False, "error": "timeout"}],
    }

    wb = build_workbench(processos=[], prazos=[], out_root=tmp_path, sync_status=sync_status)

    assert wb["sync_status"] == sync_status
