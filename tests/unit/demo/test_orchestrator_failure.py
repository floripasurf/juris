"""Tests for orchestrator failure semantics + DemoResult.succeeded.

Codex flagged that a failed draft must produce a non-success DemoResult and a
non-zero CLI exit. These tests pin the exact contract:

    - succeeded == True only when draft is not None AND no errors.
    - When the drafter raises, the orchestrator records the error, lets later
      code keep going, and the resulting DemoResult.succeeded is False.
    - When the analyzer raises, prazos is skipped (depends on analysis).
    - Each step's exception is captured into result.errors with a tag prefix.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from juris.demo.orchestrator import (
    DemoOrchestrator,
    DemoRequest,
    DemoResult,
    SourceMode,
    _can_degrade_to_deterministic_rascunho,
    derive_demo_mode,
)
from juris.demo.output_mode import OutputMode
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.persistence.audit import AuditLog
from juris.repertory.peticoes.models import TipoPeticao


def _processo() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj="0001234-56.2026.8.13.0001",
        classe="Procedimento Comum Cível",
        tribunal="tjmg",
        movimentos=[
            Movimento(
                data_hora=datetime.now(UTC),
                tipo="movimentoNacional",
                codigo_nacional=12265,
                descricao="Citação realizada (DEMO).",
                id_movimento="m1",
            ),
        ],
    )


def _request() -> DemoRequest:
    return DemoRequest(
        numero_cnj="0001234-56.2026.8.13.0001",
        tipo_peticao=TipoPeticao.CONTESTACAO,
        tribunal="tjmg",
        source=SourceMode.FIXTURE,
    )


def _result_skeleton(
    tmp_path: Path, *, is_demo_mode: bool = True
) -> tuple[DemoResult, Path]:
    out_dir = tmp_path / "DEMO-x"
    out_dir.mkdir(parents=True)
    audit_path = tmp_path / "audit.jsonl"
    audit_path.touch()
    started = datetime.now(UTC)
    res = DemoResult(
        request=_request(),
        processo=_processo(),
        out_dir=out_dir,
        is_demo_mode=is_demo_mode,
        started_at=started,
        finished_at=started,
        duration_seconds=0.0,
        audit_log_path=audit_path,
    )
    return res, audit_path


class TestDemoResultSucceeded:
    def test_no_draft_means_not_succeeded(self, tmp_path: Path) -> None:
        res, _ = _result_skeleton(tmp_path)
        # draft=None by default
        assert res.draft is None
        assert res.succeeded is False

    def test_draft_with_errors_means_not_succeeded(self, tmp_path: Path) -> None:
        res, _ = _result_skeleton(tmp_path)
        res.draft = MagicMock()
        res.errors = ["analyze: boom"]
        assert res.succeeded is False

    def test_draft_no_errors_means_succeeded(self, tmp_path: Path) -> None:
        res, _ = _result_skeleton(tmp_path)
        res.draft = MagicMock()
        res.errors = []
        assert res.succeeded is True


class TestOrchestratorErrorPaths:
    def _build(self, audit_path: Path) -> tuple[DemoOrchestrator, AuditLog]:
        llm = MagicMock()
        llm.model_name = "test-llm"
        repertory = MagicMock()
        audit = AuditLog(audit_path)
        return DemoOrchestrator(llm=llm, repertory=repertory, audit=audit), audit

    def test_drafter_failure_records_error_and_keeps_going(
        self, tmp_path: Path
    ) -> None:
        skeleton, audit_path = _result_skeleton(tmp_path)
        orch, _ = self._build(audit_path)

        # Force the drafter wrapper to raise.
        orch._run_drafter = AsyncMock(side_effect=RuntimeError("drafter boom"))  # type: ignore[method-assign]

        # Stub analyzer to succeed quickly.
        fake_analysis = MagicMock(analyzed=[], actionable=[], summary="ok")
        with (
            patch(
                "juris.demo.orchestrator.analyze_processo",
                AsyncMock(return_value=fake_analysis),
            ),
            patch("juris.demo.orchestrator.compute_prazos") as mock_prazos,
        ):
            mock_prazos.return_value = MagicMock(prazos=[], summary="ok")
            result = asyncio.run(
                orch.run(
                    skeleton.request,
                    processo=skeleton.processo,
                    out_dir=skeleton.out_dir,
                    is_demo_mode=True,
                )
            )

        assert result.draft is None
        assert any(e.startswith("draft:") for e in result.errors)
        assert "drafter boom" in result.errors[0]
        assert result.succeeded is False

    def test_analyzer_failure_skips_prazos_and_marks_error(
        self, tmp_path: Path
    ) -> None:
        skeleton, audit_path = _result_skeleton(tmp_path)
        orch, _ = self._build(audit_path)

        orch._run_drafter = AsyncMock(return_value=MagicMock(  # type: ignore[method-assign]
            revisions=0, citations_used=[], audit_entry_ids=[],
            research_summary="", reviewer_report=None, contraponto_section="",
        ))

        with (
            patch(
                "juris.demo.orchestrator.analyze_processo",
                AsyncMock(side_effect=ValueError("bad movements")),
            ),
            patch("juris.demo.orchestrator.compute_prazos") as mock_prazos,
        ):
            result = asyncio.run(
                orch.run(
                    skeleton.request,
                    processo=skeleton.processo,
                    out_dir=skeleton.out_dir,
                    is_demo_mode=True,
                )
            )

        assert result.analysis is None
        assert result.prazo_report is None
        assert any(e.startswith("analyze:") for e in result.errors)
        # compute_prazos must NOT have been called when analysis is missing.
        mock_prazos.assert_not_called()
        # Drafter still ran, so draft is present, but errors keep succeeded False.
        assert result.draft is not None
        assert result.succeeded is False

    def test_prazos_failure_does_not_block_drafter(self, tmp_path: Path) -> None:
        skeleton, audit_path = _result_skeleton(tmp_path)
        orch, _ = self._build(audit_path)

        orch._run_drafter = AsyncMock(return_value=MagicMock(  # type: ignore[method-assign]
            revisions=0, citations_used=[], audit_entry_ids=[],
            research_summary="", reviewer_report=None, contraponto_section="",
        ))

        fake_analysis = MagicMock(analyzed=[], actionable=[], summary="ok")
        with (
            patch(
                "juris.demo.orchestrator.analyze_processo",
                AsyncMock(return_value=fake_analysis),
            ),
            patch(
                "juris.demo.orchestrator.compute_prazos",
                side_effect=RuntimeError("prazo blew up"),
            ),
        ):
            result = asyncio.run(
                orch.run(
                    skeleton.request,
                    processo=skeleton.processo,
                    out_dir=skeleton.out_dir,
                    is_demo_mode=True,
                )
            )

        assert result.prazo_report is None
        assert any(e.startswith("prazos:") for e in result.errors)
        assert result.draft is not None
        assert result.succeeded is False

    def test_rascunho_mode_degrades_when_local_llm_unavailable(self, tmp_path: Path) -> None:
        skeleton, audit_path = _result_skeleton(tmp_path, is_demo_mode=False)
        request = replace(
            skeleton.request,
            source=SourceMode.DATAJUD,
            output_mode=OutputMode.RASCUNHO_PESQUISA,
        )
        orch, audit = self._build(audit_path)

        request_error = httpx.ConnectError(
            "All connection attempts failed",
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        )
        orch._run_drafter = AsyncMock(  # type: ignore[method-assign]
            side_effect=request_error
        )

        fake_analysis = MagicMock(
            analyzed=[],
            actionable=[],
            summary="rule-only analysis",
            total_movimentos=1,
            rule_classified=1,
            llm_calls=0,
        )
        with (
            patch(
                "juris.demo.orchestrator.analyze_processo",
                AsyncMock(return_value=fake_analysis),
            ),
            patch("juris.demo.orchestrator.compute_prazos") as mock_prazos,
        ):
            mock_prazos.return_value = MagicMock(prazos=[], summary="ok")
            result = asyncio.run(
                orch.run(
                    request,
                    processo=skeleton.processo,
                    out_dir=skeleton.out_dir,
                    is_demo_mode=False,
                )
            )

        assert result.errors == []
        assert result.draft is not None
        assert "modo determinístico sem LLM" in result.draft.research_summary
        assert result.succeeded is True
        assert result.degraded is True
        assert "All connection attempts failed" in result.degradation_reason
        assert any(
            e.event_type == "demo.rascunho_deterministic_fallback"
            for e in audit.read_all()
        )

    def test_rascunho_mode_does_not_hide_non_llm_connection_failure(self, tmp_path: Path) -> None:
        skeleton, audit_path = _result_skeleton(tmp_path, is_demo_mode=False)
        request = replace(
            skeleton.request,
            source=SourceMode.DATAJUD,
            output_mode=OutputMode.RASCUNHO_PESQUISA,
        )
        orch, _ = self._build(audit_path)

        qdrant_error = httpx.ConnectError(
            "All connection attempts failed",
            request=httpx.Request("GET", "http://localhost:6333/collections"),
        )
        orch._run_drafter = AsyncMock(side_effect=qdrant_error)  # type: ignore[method-assign]

        fake_analysis = MagicMock(analyzed=[], actionable=[], summary="ok")
        with (
            patch(
                "juris.demo.orchestrator.analyze_processo",
                AsyncMock(return_value=fake_analysis),
            ),
            patch("juris.demo.orchestrator.compute_prazos") as mock_prazos,
        ):
            mock_prazos.return_value = MagicMock(prazos=[], summary="ok")
            result = asyncio.run(
                orch.run(
                    request,
                    processo=skeleton.processo,
                    out_dir=skeleton.out_dir,
                    is_demo_mode=False,
                )
            )

        assert result.draft is None
        assert result.degraded is False
        assert result.degradation_reason == ""
        assert any(e.startswith("draft:") for e in result.errors)
        assert result.succeeded is False

    def test_rascunho_mode_does_not_degrade_on_ollama_read_timeout(self) -> None:
        request = replace(_request(), output_mode=OutputMode.RASCUNHO_PESQUISA)
        timeout_error = httpx.ReadTimeout(
            "generation timed out",
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        )

        assert _can_degrade_to_deterministic_rascunho(request, timeout_error) is False

    def test_minuta_mode_does_not_hide_local_llm_failure(self, tmp_path: Path) -> None:
        skeleton, audit_path = _result_skeleton(tmp_path, is_demo_mode=False)
        request = replace(
            skeleton.request,
            source=SourceMode.DATAJUD,
            output_mode=OutputMode.MINUTA_SUGERIDA,
        )
        orch, _ = self._build(audit_path)

        orch._run_drafter = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("All connection attempts failed")
        )

        fake_analysis = MagicMock(analyzed=[], actionable=[], summary="ok")
        with (
            patch(
                "juris.demo.orchestrator.analyze_processo",
                AsyncMock(return_value=fake_analysis),
            ),
            patch("juris.demo.orchestrator.compute_prazos") as mock_prazos,
        ):
            mock_prazos.return_value = MagicMock(prazos=[], summary="ok")
            result = asyncio.run(
                orch.run(
                    request,
                    processo=skeleton.processo,
                    out_dir=skeleton.out_dir,
                    is_demo_mode=False,
                )
            )

        assert result.draft is None
        assert any(e.startswith("draft:") for e in result.errors)
        assert result.succeeded is False


class TestDeriveDemoMode:
    def test_fixture_forces_demo_mode(self) -> None:
        assert derive_demo_mode(SourceMode.FIXTURE) is True

    def test_datajud_is_real_mode(self) -> None:
        assert derive_demo_mode(SourceMode.DATAJUD) is False

    def test_mni_is_real_mode(self) -> None:
        # MNI is not implemented yet, but the rule says only FIXTURE forces DEMO.
        assert derive_demo_mode(SourceMode.MNI) is False
