"""Tests for `juris repertory status` — text + --json output, exit codes.

The command's contract is:

- Reads `repertory.db` without ever creating or writing to it.
- Exits 0 when the corpus is ready (>= thresholds).
- Exits 1 when the corpus is missing, empty, or below thresholds, so
  CI/automation/runbook scripts can branch on it.
- `--json` produces a stable shape consumable by `jq`.
- Surfaces a legacy-path warning when both canonical and legacy DBs exist
  but never moves data automatically.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from juris.cli.main import app
from juris.repertory.readiness import (
    ENV_MIN_CHUNKS,
    ENV_MIN_SOURCE_TYPES,
    ENV_REPERTORY_PATH,
    LEGACY_REPERTORY_PATH,
    resolve_repertory_path,
)

runner = CliRunner()


def _seed(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
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
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ENV_REPERTORY_PATH, ENV_MIN_CHUNKS, ENV_MIN_SOURCE_TYPES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("JURIS_HOME", raising=False)


class TestExitCodes:
    def test_missing_db_exits_nonzero(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "repertory",
                "status",
                "--path",
                str(tmp_path / "missing.db"),
            ],
        )
        assert result.exit_code == 1, result.output
        assert "não encontrado" in result.output or "nao encontrado" in result.output

    def test_empty_db_exits_nonzero(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        _seed(db, rows=[])
        result = runner.invoke(
            app, ["repertory", "status", "--path", str(db)]
        )
        assert result.exit_code == 1, result.output

    def test_populated_db_exits_zero(self, tmp_path: Path) -> None:
        db = tmp_path / "good.db"
        _seed(
            db,
            [
                ("c1", "s1", "sumula_vinculante", "x"),
                ("c2", "s2", "modelo_peticao", "y"),
                ("c3", "s3", "modelo_peticao", "z"),
            ],
        )
        result = runner.invoke(
            app,
            [
                "repertory",
                "status",
                "--path",
                str(db),
                "--min-chunks",
                "2",
                "--min-source-types",
                "2",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "sim" in result.output


def test_repertory_backfill_embeddings_populates_legacy_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "legacy.db"
    _seed(
        db,
        [
            ("c1", "s1", "sumula_vinculante", "honorários advocatícios"),
            ("c2", "s2", "acordao_publicado", "prescrição intercorrente"),
        ],
    )
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))

    class _FakeEmbedder:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if "honorários" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr("juris.repertory.embeddings.LegalEmbedder", _FakeEmbedder)

    result = runner.invoke(app, ["repertory", "backfill-embeddings", "--batch-size", "1"])

    assert result.exit_code == 0, result.output
    assert "Embeddings atualizados" in result.output
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0] == 2
    finally:
        conn.close()


class TestTextOutput:
    def test_shows_breakdown_table(self, tmp_path: Path) -> None:
        db = tmp_path / "with-breakdown.db"
        _seed(
            db,
            [
                ("c1", "s1", "sumula_vinculante", "x"),
                ("c2", "s2", "modelo_peticao", "y"),
            ],
        )
        result = runner.invoke(
            app,
            [
                "repertory",
                "status",
                "--path",
                str(db),
                "--min-chunks",
                "1",
                "--min-source-types",
                "2",
            ],
        )
        assert "sumula_vinculante" in result.output
        assert "modelo_peticao" in result.output

    def test_shows_db_path(self, tmp_path: Path) -> None:
        # Use a short filename inside tmp_path so Rich's terminal wrapping
        # doesn't split the absolute path across lines.
        db = tmp_path / "labelled.db"
        _seed(db, [("c1", "s1", "sumula", "x")])
        result = runner.invoke(
            app, ["repertory", "status", "--path", str(db)]
        )
        # Rich may wrap the path across lines; check that the filename
        # still appears verbatim in the (newline-collapsed) output.
        collapsed = result.output.replace("\n", "")
        assert db.name in collapsed
        assert "Repertory" in result.output


class TestJsonOutput:
    def test_json_shape_for_populated_db(self, tmp_path: Path) -> None:
        db = tmp_path / "json-good.db"
        _seed(
            db,
            [
                ("c1", "s1", "sumula_vinculante", "x"),
                ("c2", "s2", "modelo_peticao", "y"),
            ],
        )
        result = runner.invoke(
            app,
            [
                "repertory",
                "status",
                "--path",
                str(db),
                "--min-chunks",
                "1",
                "--min-source-types",
                "2",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["is_ready"] is True
        assert payload["chunk_count"] == 2
        assert payload["source_count"] == 2
        assert payload["source_type_count"] == 2
        assert payload["thresholds"] == {"min_chunks": 1, "min_source_types": 2}
        assert payload["not_ready_reason"] is None

    def test_json_shape_for_missing_db(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "repertory",
                "status",
                "--path",
                str(tmp_path / "missing.db"),
                "--json",
            ],
        )
        # Exit nonzero but JSON still parseable.
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["exists"] is False
        assert payload["is_ready"] is False
        assert payload["chunk_count"] == 0


class TestEnvOverrides:
    def test_default_repertory_path_honors_juris_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JURIS_HOME", str(tmp_path))

        assert resolve_repertory_path() == tmp_path / "repertory.db"

    def test_env_repertory_path_used_when_no_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "from-env.db"
        _seed(db, [("c1", "s1", "sumula", "x")])
        monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
        result = runner.invoke(
            app,
            ["repertory", "status", "--min-chunks", "1", "--min-source-types", "1"],
        )
        assert result.exit_code == 0
        # Rich may wrap the path; check for the filename in collapsed output.
        assert db.name in result.output.replace("\n", "")


class TestLegacyPathWarning:
    def test_warns_when_legacy_db_exists_under_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Build a populated DB at the legacy location relative to a
        # synthetic cwd, and a separate (empty) canonical location.
        legacy_dir = tmp_path / LEGACY_REPERTORY_PATH.parent
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy = tmp_path / LEGACY_REPERTORY_PATH
        legacy.write_bytes(b"")  # any file is enough for detection

        canonical = tmp_path / "elsewhere.db"
        # Point the command at the canonical location so it inspects
        # there, but cd into tmp_path so detect_legacy_path can find the
        # legacy DB at "data/repertory.db".
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            ["repertory", "status", "--path", str(canonical)],
        )
        assert "banco legado" in result.output

    def test_no_warning_when_canonical_is_legacy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy_dir = tmp_path / LEGACY_REPERTORY_PATH.parent
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy = tmp_path / LEGACY_REPERTORY_PATH
        _seed(legacy, [("c1", "s1", "sumula", "x")])
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app, ["repertory", "status", "--path", str(legacy)]
        )
        assert "banco legado" not in result.output
