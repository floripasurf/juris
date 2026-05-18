"""Tests for the `juris demo` CLI command — exit codes + DEMO output naming.

The single most important behavior pinned here is Codex's review point:
when the demo result is not succeeded, the CLI must exit nonzero. The bug
this guards against is a lawyer-facing demo that fails silently and looks
like it worked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from juris.cli.main import app
from juris.demo.disclaimer import DEMO_DIR_PREFIX
from juris.demo.orchestrator import DemoRequest, DemoResult, SourceMode
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.repertory.peticoes.models import TipoPeticao

runner = CliRunner()


def _processo(cnj: str = "0001234-56.2026.8.13.0001") -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj=cnj,
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


def _success_result(
    *,
    cnj: str,
    out_dir: Path,
    audit_path: Path,
    is_demo_mode: bool = True,
) -> DemoResult:
    request = DemoRequest(
        numero_cnj=cnj,
        tipo_peticao=TipoPeticao.CONTESTACAO,
        tribunal="tjmg",
        source=SourceMode.FIXTURE if is_demo_mode else SourceMode.DATAJUD,
    )
    started = datetime.now(UTC)
    return DemoResult(
        request=request,
        processo=_processo(cnj),
        out_dir=out_dir,
        is_demo_mode=is_demo_mode,
        started_at=started,
        finished_at=started,
        duration_seconds=1.0,
        audit_log_path=audit_path,
        draft=MagicMock(  # truthy => result.succeeded == True
            revisions=0,
            citations_used=[],
            audit_entry_ids=[],
            research_summary="",
            reviewer_report=None,
            contraponto_section="",
        ),
    )


def _failed_result(
    *, cnj: str, out_dir: Path, audit_path: Path, is_demo_mode: bool = True
) -> DemoResult:
    request = DemoRequest(
        numero_cnj=cnj,
        tipo_peticao=TipoPeticao.CONTESTACAO,
        tribunal="tjmg",
        source=SourceMode.FIXTURE if is_demo_mode else SourceMode.DATAJUD,
    )
    started = datetime.now(UTC)
    return DemoResult(
        request=request,
        processo=_processo(cnj),
        out_dir=out_dir,
        is_demo_mode=is_demo_mode,
        started_at=started,
        finished_at=started,
        duration_seconds=0.5,
        audit_log_path=audit_path,
        draft=None,                 # absent draft => not succeeded
        errors=["draft: drafter blew up"],
    )


@pytest.fixture()
def _stub_demo_environment(tmp_path: Path):
    """Patch the heavy-weight collaborators the demo CLI sets up.

    Returns a callable that accepts a `result_factory(cnj, out_dir, audit_path)
    -> DemoResult` and patches `run_demo` to return that result.
    """

    def _setup(result_factory):
        captured: dict[str, Path] = {}

        def fake_run_demo(request, **kwargs):
            captured["out_dir"] = kwargs["out_dir"]
            captured["audit_path"] = kwargs["audit_path"]
            return result_factory(
                cnj=request.numero_cnj,
                out_dir=kwargs["out_dir"],
                audit_path=kwargs["audit_path"],
                is_demo_mode=kwargs["is_demo_mode"],
            )

        async def _async_run_demo(*args, **kwargs):
            return fake_run_demo(*args, **kwargs)

        patches = [
            patch("juris.llm.ollama.OllamaLLM", MagicMock()),
            patch("juris.repertory.embeddings.LegalEmbedder", MagicMock()),
            patch("juris.repertory.vector_store.LocalFTSStore", MagicMock()),
            patch(
                "juris.repertory.retrieval.reranker.CrossEncoderReranker",
                MagicMock(),
            ),
            patch(
                "juris.repertory.retrieval.hybrid.HybridRetriever", MagicMock()
            ),
            patch(
                "juris.repertory.retrieval.service.RepertoryService", MagicMock()
            ),
            patch(
                "juris.demo.orchestrator.load_processo",
                return_value=_processo(),
            ),
            patch("juris.demo.run_demo", side_effect=_async_run_demo),
            patch(
                "juris.demo.artifacts.write_artifacts",
                return_value={"draft.md": "x"},
            ),
        ]
        return patches, captured

    return _setup


class TestDemoExitCode:
    def test_succeeded_run_exits_zero(self, tmp_path: Path, _stub_demo_environment):
        cnj = "0001234-56.2026.8.13.0001"
        patches, captured = _stub_demo_environment(_success_result)
        with _ExitStack(*patches):
            result = runner.invoke(
                app,
                [
                    "demo",
                    cnj,
                    "contestacao",
                    "--source",
                    "fixture",
                    "--out",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Concluído" in result.output

    def test_failed_run_exits_nonzero(self, tmp_path: Path, _stub_demo_environment):
        """The single bug Codex flagged: failed demo must exit nonzero."""
        cnj = "0001234-56.2026.8.13.0001"
        patches, captured = _stub_demo_environment(_failed_result)
        with _ExitStack(*patches):
            result = runner.invoke(
                app,
                [
                    "demo",
                    cnj,
                    "contestacao",
                    "--source",
                    "fixture",
                    "--out",
                    str(tmp_path),
                ],
            )
        assert result.exit_code != 0
        assert "Falhou" in result.output
        assert "draft: drafter blew up" in result.output


class TestDemoOutputNaming:
    def test_fixture_source_uses_demo_prefix_dir(
        self, tmp_path: Path, _stub_demo_environment
    ):
        cnj = "0001234-56.2026.8.13.0001"
        patches, captured = _stub_demo_environment(_success_result)
        with _ExitStack(*patches):
            runner.invoke(
                app,
                [
                    "demo",
                    cnj,
                    "contestacao",
                    "--source",
                    "fixture",
                    "--out",
                    str(tmp_path),
                ],
            )
        assert captured["out_dir"].name.startswith(DEMO_DIR_PREFIX)
        assert cnj in captured["out_dir"].name

    def test_demo_banner_printed_for_fixture_runs(
        self, tmp_path: Path, _stub_demo_environment
    ):
        cnj = "0001234-56.2026.8.13.0001"
        patches, captured = _stub_demo_environment(_success_result)
        with _ExitStack(*patches):
            result = runner.invoke(
                app,
                [
                    "demo",
                    cnj,
                    "contestacao",
                    "--source",
                    "fixture",
                    "--out",
                    str(tmp_path),
                ],
            )
        assert "MODO DEMONSTRAÇÃO ATIVO" in result.output
        # Reminder footer also printed when demo mode.
        assert "Não pode ser protocolada" in result.output


class TestDemoDataJudSafetyOptions:
    def test_datajud_source_passes_no_cache_to_loader(self, tmp_path: Path, monkeypatch):
        cnj = "0001234-56.2026.8.13.0001"
        captured: dict[str, object] = {}

        def fake_load(numero_cnj, tribunal, source, **kwargs):
            captured.update(kwargs)
            return _processo(cnj)

        def fake_status(_path):
            return MagicMock(is_ready=True, not_ready_reason=None)

        async def fake_run_demo(request, **kwargs):
            return _success_result(
                cnj=request.numero_cnj,
                out_dir=kwargs["out_dir"],
                audit_path=kwargs["audit_path"],
                is_demo_mode=kwargs["is_demo_mode"],
            )

        with (
            patch("juris.repertory.readiness.read_status", side_effect=fake_status),
            patch("juris.llm.ollama.OllamaLLM", MagicMock()),
            patch("juris.repertory.embeddings.LegalEmbedder", MagicMock()),
            patch("juris.repertory.vector_store.LocalFTSStore", MagicMock()),
            patch("juris.repertory.retrieval.reranker.CrossEncoderReranker", MagicMock()),
            patch("juris.repertory.retrieval.hybrid.HybridRetriever", MagicMock()),
            patch("juris.repertory.retrieval.service.RepertoryService", MagicMock()),
            patch("juris.demo.orchestrator.load_processo", side_effect=fake_load),
            patch("juris.demo.run_demo", side_effect=fake_run_demo),
            patch("juris.demo.artifacts.write_artifacts", return_value={"draft.md": "x"}),
        ):
            result = runner.invoke(
                app,
                [
                    "demo",
                    cnj,
                    "contestacao",
                    "--source",
                    "datajud",
                    "--no-cache",
                    "--out",
                    str(tmp_path),
                ],
            )

        assert result.exit_code == 0, result.output
        assert captured["use_cache"] is False


class TestDemoInputValidation:
    def test_invalid_tipo_exits_nonzero(self, tmp_path: Path) -> None:
        """A bad petition type must exit with code 1, not 0."""
        result = runner.invoke(
            app,
            [
                "demo",
                "0001234-56.2026.8.13.0001",
                "not_a_real_type",
                "--source",
                "fixture",
                "--out",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert "Tipo inválido" in result.output

    def test_invalid_source_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "demo",
                "0001234-56.2026.8.13.0001",
                "contestacao",
                "--source",
                "bogus",
                "--out",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert "--source inválido" in result.output

    def test_invalid_cnj_format_rejected_before_pipeline(
        self, tmp_path: Path
    ) -> None:
        """A malformed CNJ must be rejected before any artifacts are written.

        Without this guard, a lawyer mistyping a CNJ would silently get demo
        output with their typo baked into the directory name and artifacts.
        """
        result = runner.invoke(
            app,
            [
                "demo",
                "INVALID-CNJ",
                "contestacao",
                "--source",
                "fixture",
                "--out",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert "Número CNJ inválido" in result.output
        # No output dir should have been created — fail-fast before mkdir.
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Helper: nested patch context manager (so the test body stays readable).
# ---------------------------------------------------------------------------


class _ExitStack:
    """Apply a list of unittest.mock.patch objects as a single context."""

    def __init__(self, *patches) -> None:
        self._patches = list(patches)
        self._entered: list = []

    def __enter__(self) -> _ExitStack:
        for p in self._patches:
            self._entered.append(p.__enter__())
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for p in reversed(self._patches):
            p.__exit__(exc_type, exc, tb)
