"""Tests for the MNI source wiring in the `juris demo` CLI command."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from juris.cli.main import app
from juris.demo.orchestrator import DemoResult
from juris.mni.parsers.processo import Movimento, ProcessoDomain

runner = CliRunner()
_CNJ = "5082351-40.2017.8.13.0024"


def _processo() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj=_CNJ,
        tribunal="tjmg",
        movimentos=[Movimento(data_hora=datetime.now(UTC), tipo="nacional", codigo_nacional=1051)],
    )


def test_mni_source_without_cpf_exits_nonzero(tmp_path: Path) -> None:
    """MNI needs the constituted lawyer's CPF (checked once the corpus is ready)."""
    with ExitStack() as stack:
        stack.enter_context(
            patch("juris.repertory.readiness.resolve_repertory_path", return_value=tmp_path / "rep.db")
        )
        stack.enter_context(patch("juris.repertory.readiness.detect_legacy_path", return_value=None))
        stack.enter_context(
            patch("juris.repertory.readiness.read_status", return_value=MagicMock(is_ready=True))
        )
        result = runner.invoke(
            app,
            ["demo", _CNJ, "contestacao", "--source", "mni", "--out", str(tmp_path)],
        )
    assert result.exit_code == 1, result.output
    assert "cpf" in result.output.lower()


def test_mni_source_threads_credentials_to_load_processo(tmp_path: Path) -> None:
    """--cpf, resolved PJe password and --pin must reach load_processo."""
    captured: dict[str, object] = {}

    def fake_load(*args, **kwargs):
        captured.update(kwargs)
        return _processo()

    async def fake_run_demo(request, **kwargs):
        return DemoResult(
            request=request,
            processo=_processo(),
            out_dir=kwargs["out_dir"],
            is_demo_mode=kwargs["is_demo_mode"],
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            duration_seconds=0.1,
            audit_log_path=kwargs["audit_path"],
            draft=MagicMock(revisions=0),
        )

    patches = [
        patch("juris.repertory.readiness.resolve_repertory_path", return_value=tmp_path / "rep.db"),
        patch("juris.repertory.readiness.detect_legacy_path", return_value=None),
        patch("juris.repertory.readiness.read_status", return_value=MagicMock(is_ready=True)),
        patch("juris.llm.ollama.OllamaLLM", MagicMock()),
        patch("juris.repertory.embeddings.LegalEmbedder", MagicMock()),
        patch("juris.repertory.vector_store.LocalFTSStore", MagicMock()),
        patch("juris.repertory.retrieval.reranker.CrossEncoderReranker", MagicMock()),
        patch("juris.repertory.retrieval.hybrid.HybridRetriever", MagicMock()),
        patch("juris.repertory.retrieval.service.RepertoryService", MagicMock()),
        patch("juris.cli.main._get_senha", return_value="pjepass"),
        patch("juris.demo.orchestrator.load_processo", side_effect=fake_load),
        patch("juris.demo.run_demo", side_effect=fake_run_demo),
        patch("juris.demo.artifacts.write_artifacts", return_value={"draft.md": "x"}),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        result = runner.invoke(
            app,
            [
                "demo", _CNJ, "contestacao",
                "--source", "mni",
                "--tribunal", "tjmg",
                "--cpf", "07671039632",
                "--pin", "1234",
                "--out", str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert captured.get("cpf") == "07671039632"
    assert captured.get("senha") == "pjepass"
    assert captured.get("token_pin") == "1234"
