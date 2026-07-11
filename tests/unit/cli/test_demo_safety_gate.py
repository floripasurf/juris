"""Tests for the `juris demo` real-source corpus safety gate.

Sprint 16's headline behavior: a real-source demo must REFUSE to run when
the corpus is missing or below threshold, so the lawyer-facing pipeline
never produces a "draft" with empty retrieval. Fixture mode stays open —
its output is loud-banner DEMO and not protocolável.

These tests stub all heavy dependencies (LLM, embedder, retrieval, run_demo)
so they exercise only the CLI's preflight branch.
"""

from __future__ import annotations

import sqlite3
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from juris.cli.main import app
from juris.repertory.readiness import (
    ENV_MIN_CHUNKS,
    ENV_MIN_SOURCE_TYPES,
    ENV_REPERTORY_PATH,
)

runner = CliRunner()


def _seed_ready_corpus(path: Path) -> None:
    """Build a tiny repertory.db that passes the default thresholds when
    those defaults are themselves overridden to small values for tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_type TEXT,
                text TEXT NOT NULL,
                metadata TEXT,
                position INTEGER DEFAULT 0
            );
            """
        )
        conn.executemany(
            "INSERT INTO chunks (chunk_id, source_id, source_type, text) "
            "VALUES (?, ?, ?, ?)",
            [
                ("c1", "s1", "sumula_vinculante", "x"),
                ("c2", "s2", "modelo_peticao", "y"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ENV_REPERTORY_PATH, ENV_MIN_CHUNKS, ENV_MIN_SOURCE_TYPES):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def _isolate_repertory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the readiness module at a tmp DB and chdir to an empty cwd
    so the test can't accidentally see the project's data/repertory.db
    via legacy detection."""
    db = tmp_path / "repertory.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    return db


def _stub_demo_pipeline_patches(tmp_path: Path):
    """Patches that stub out all collaborators after the safety gate so
    the test never touches LLMs, embedders, or real retrieval."""
    from datetime import UTC, datetime

    from juris.demo.orchestrator import DemoRequest, DemoResult, SourceMode
    from juris.mni.parsers.processo import Movimento, ProcessoDomain
    from juris.repertory.peticoes.models import TipoPeticao

    def _processo(cnj: str) -> ProcessoDomain:
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

    def _success_factory(cnj: str, out_dir: Path, audit_path: Path) -> DemoResult:
        request = DemoRequest(
            numero_cnj=cnj,
            tipo_peticao=TipoPeticao.CONTESTACAO,
            tribunal="tjmg",
            source=SourceMode.DATAJUD,
        )
        started = datetime.now(UTC)
        return DemoResult(
            request=request,
            processo=_processo(cnj),
            out_dir=out_dir,
            is_demo_mode=False,
            started_at=started,
            finished_at=started,
            duration_seconds=1.0,
            audit_log_path=audit_path,
            draft=MagicMock(
                revisions=0,
                citations_used=[],
                audit_entry_ids=[],
                research_summary="",
                reviewer_report=None,
                contraponto_section="",
            ),
        )

    async def _async_run_demo(request, **kwargs):
        return _success_factory(
            request.numero_cnj, kwargs["out_dir"], kwargs["audit_path"]
        )

    return [
        patch("juris.llm.ollama.OllamaLLM", MagicMock()),
        patch("juris.repertory.embeddings.LegalEmbedder", MagicMock()),
        patch("juris.repertory.vector_store.LocalFTSStore", MagicMock()),
        patch(
            "juris.repertory.retrieval.reranker.CrossEncoderReranker",
            MagicMock(),
        ),
        patch("juris.repertory.retrieval.hybrid.HybridRetriever", MagicMock()),
        patch(
            "juris.repertory.retrieval.service.RepertoryService", MagicMock()
        ),
        patch(
            "juris.demo.orchestrator.load_processo",
            return_value=_processo("0001234-56.2026.8.13.0001"),
        ),
        patch("juris.demo.run_demo", side_effect=_async_run_demo),
        patch(
            "juris.demo.artifacts.write_artifacts",
            return_value={"draft.md": "x"},
        ),
    ]


CNJ = "0001234-56.2026.8.13.0001"


class TestRealSourceGate:
    def test_datajud_with_missing_corpus_aborts(
        self, tmp_path: Path, _isolate_repertory: Path
    ) -> None:
        # Don't seed: env points at a non-existent DB.
        result = runner.invoke(
            app,
            [
                "demo",
                CNJ,
                "contestacao",
                "--source",
                "datajud",
                "--out",
                str(tmp_path / "out"),
            ],
        )
        assert result.exit_code == 1, result.output
        assert "Corpus não está pronto" in result.output
        assert "Demo abortado" in result.output

    def test_datajud_with_empty_corpus_aborts(
        self, tmp_path: Path, _isolate_repertory: Path
    ) -> None:
        # Build an empty DB on disk.
        _isolate_repertory.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(_isolate_repertory).close()
        result = runner.invoke(
            app,
            [
                "demo",
                CNJ,
                "contestacao",
                "--source",
                "datajud",
                "--out",
                str(tmp_path / "out"),
            ],
        )
        assert result.exit_code == 1
        assert "Corpus não está pronto" in result.output

    def test_mni_source_also_gated(
        self, tmp_path: Path, _isolate_repertory: Path
    ) -> None:
        # MNI now performs a real read downstream, but the corpus gate must
        # still fire FIRST when the corpus is missing — that's the correct
        # order (no --cpf is needed to reach the gate).
        result = runner.invoke(
            app,
            [
                "demo",
                CNJ,
                "contestacao",
                "--source",
                "mni",
                "--out",
                str(tmp_path / "out"),
            ],
        )
        assert result.exit_code == 1
        assert "Corpus não está pronto" in result.output

    def test_fixture_source_bypasses_gate(
        self,
        tmp_path: Path,
        _isolate_repertory: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fixture mode is the documented escape hatch — it must run even
        with no corpus, because its output is loud DEMO and not fileable."""
        patches = _stub_demo_pipeline_patches(tmp_path)
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = runner.invoke(
                app,
                [
                    "demo",
                    CNJ,
                    "contestacao",
                    "--source",
                    "fixture",
                    "--out",
                    str(tmp_path / "out"),
                ],
            )
        assert "Corpus não está pronto" not in result.output

    def test_datajud_with_ready_corpus_passes_gate(
        self,
        tmp_path: Path,
        _isolate_repertory: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Seed and lower thresholds via env so the tiny test corpus passes.
        _seed_ready_corpus(_isolate_repertory)
        monkeypatch.setenv(ENV_MIN_CHUNKS, "1")
        monkeypatch.setenv(ENV_MIN_SOURCE_TYPES, "1")
        patches = _stub_demo_pipeline_patches(tmp_path)
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = runner.invoke(
                app,
                [
                    "demo",
                    CNJ,
                    "contestacao",
                    "--source",
                    "datajud",
                    "--out",
                    str(tmp_path / "out"),
                ],
            )
        assert "Corpus não está pronto" not in result.output
        assert result.exit_code == 0, result.output


class TestLegacyPathWarning:
    def test_warns_when_legacy_db_present_under_cwd(
        self,
        tmp_path: Path,
        _isolate_repertory: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build the legacy-path DB inside tmp_path (cwd), distinct from
        # the canonical one set by _isolate_repertory.
        legacy = tmp_path / "cwd" / "data" / "repertory.db"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"")
        result = runner.invoke(
            app,
            [
                "demo",
                CNJ,
                "contestacao",
                "--source",
                "datajud",
                "--out",
                str(tmp_path / "out"),
            ],
        )
        # Gate still fires (no canonical corpus), but the legacy warning
        # should appear in the output to point operator at the old DB.
        assert "banco legado" in result.output
