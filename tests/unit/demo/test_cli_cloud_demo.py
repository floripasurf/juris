"""Tests for the `juris demo --cli-cloud` subscription adapter path."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from juris.cli.main import app
from juris.demo.orchestrator import DemoResult
from juris.llm.local_cli import LocalCliLLM
from juris.mni.parsers.processo import Movimento, ProcessoDomain

runner = CliRunner()

CNJ = "0001234-56.2026.8.13.0001"


def _processo(cnj: str = CNJ) -> ProcessoDomain:
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


def test_demo_cli_cloud_passes_subscription_adapter_and_audits_provider(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_run_demo(request: Any, **kwargs: Any) -> DemoResult:
        captured["request"] = request
        captured["llm"] = kwargs["llm"]
        started = datetime.now(UTC)
        return DemoResult(
            request=request,
            processo=_processo(request.numero_cnj),
            out_dir=kwargs["out_dir"],
            is_demo_mode=kwargs["is_demo_mode"],
            started_at=started,
            finished_at=started,
            duration_seconds=0.5,
            audit_log_path=kwargs["audit_path"],
            draft=MagicMock(
                revisions=0,
                citations_used=[],
                audit_entry_ids=[],
                research_summary="",
                reviewer_report=None,
                contraponto_section="",
            ),
        )

    with (
        patch("juris.repertory.embeddings.LegalEmbedder", MagicMock()),
        patch("juris.repertory.vector_store.LocalFTSStore", MagicMock()),
        patch("juris.repertory.retrieval.reranker.CrossEncoderReranker", MagicMock()),
        patch("juris.repertory.retrieval.hybrid.HybridRetriever", MagicMock()),
        patch("juris.repertory.retrieval.service.RepertoryService", MagicMock()),
        patch("juris.demo.orchestrator.load_processo", return_value=_processo()),
        patch("juris.demo.run_demo", side_effect=fake_run_demo),
        patch("juris.demo.artifacts.write_artifacts", return_value={"rascunho-pesquisa.md": "x"}),
    ):
        result = runner.invoke(
            app,
            [
                "demo",
                CNJ,
                "contestacao",
                "--source",
                "fixture",
                "--modo",
                "rascunho-pesquisa",
                "--skip-review",
                "--cli-cloud",
                "claude",
                "--out",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.output
    # --cli-cloud claude now defaults to Haiku on the subscription.
    assert cast(LocalCliLLM, captured["llm"]).model_name == "claude_cli_subscription:haiku"
    assert cast(Any, captured["request"]).use_cloud_llm is True
    assert cast(Any, captured["request"]).assume_no_pii is False

def test_demo_cli_cloud_rejects_non_rascunho_mode(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "demo",
            CNJ,
            "contestacao",
            "--source",
            "fixture",
            "--cli-cloud",
            "claude",
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1, result.output
    assert "--cli-cloud exige --modo rascunho-pesquisa" in result.output


def test_demo_cli_cloud_rejects_real_source_without_anonimizado(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "demo",
            CNJ,
            "contestacao",
            "--source",
            "datajud",
            "--modo",
            "rascunho-pesquisa",
            "--cli-cloud",
            "claude",
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1, result.output
    assert "--anonimizado" in result.output


def test_demo_cli_cloud_rejects_mni_source(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "demo",
            CNJ,
            "contestacao",
            "--source",
            "mni",
            "--modo",
            "rascunho-pesquisa",
            "--cli-cloud",
            "claude",
            "--anonimizado",
            "--out",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1, result.output
    assert "mni" in result.output.lower()


def test_demo_cli_cloud_allows_real_source_when_anonimizado(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_run_demo(request: Any, **kwargs: Any) -> DemoResult:
        captured["request"] = request
        captured["llm"] = kwargs["llm"]
        started = datetime.now(UTC)
        return DemoResult(
            request=request,
            processo=_processo(request.numero_cnj),
            out_dir=kwargs["out_dir"],
            is_demo_mode=kwargs["is_demo_mode"],
            started_at=started,
            finished_at=started,
            duration_seconds=0.5,
            audit_log_path=kwargs["audit_path"],
            draft=MagicMock(
                revisions=0,
                citations_used=[],
                audit_entry_ids=[],
                research_summary="",
                reviewer_report=None,
                contraponto_section="",
            ),
        )

    with (
        patch("juris.repertory.embeddings.LegalEmbedder", MagicMock()),
        patch("juris.repertory.vector_store.LocalFTSStore", MagicMock()),
        patch("juris.repertory.retrieval.reranker.CrossEncoderReranker", MagicMock()),
        patch("juris.repertory.retrieval.hybrid.HybridRetriever", MagicMock()),
        patch("juris.repertory.retrieval.service.RepertoryService", MagicMock()),
        patch("juris.repertory.readiness.detect_legacy_path", return_value=None),
        patch("juris.repertory.readiness.read_status", return_value=MagicMock(is_ready=True)),
        patch("juris.demo.orchestrator.load_processo", return_value=_processo()),
        patch("juris.demo.run_demo", side_effect=fake_run_demo),
        patch("juris.demo.artifacts.write_artifacts", return_value={"rascunho-pesquisa.md": "x"}),
    ):
        result = runner.invoke(
            app,
            [
                "demo",
                CNJ,
                "contestacao",
                "--source",
                "datajud",
                "--modo",
                "rascunho-pesquisa",
                "--skip-review",
                "--cli-cloud",
                "claude",
                "--anonimizado",
                "--out",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert cast(Any, captured["request"]).assume_no_pii is True
    assert cast(LocalCliLLM, captured["llm"]).model_name == "claude_cli_subscription:haiku"
