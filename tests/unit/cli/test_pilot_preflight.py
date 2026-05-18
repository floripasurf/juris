"""Tests for `juris pilot preflight` CLI — text + --json + exit codes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from juris.cli.main import app
from juris.repertory.readiness import ENV_REPERTORY_PATH, LEGACY_REPERTORY_PATH

runner = CliRunner()


def _seed_chunks(path: Path, count: int = 120) -> None:
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
        rows = [(f"c{i}", f"s{i % 5}", "STF" if i % 2 else "STJ", "x") for i in range(count)]
        conn.executemany(
            "INSERT INTO chunks (chunk_id, source_id, source_type, text) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Per-test isolation: temp repertory + HF cache, clean env vars, no Ollama."""
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(tmp_path / "rep.db"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / LEGACY_REPERTORY_PATH
    legacy.parent.mkdir(parents=True, exist_ok=True)
    yield


def test_preflight_text_fails_when_corpus_missing():
    result = runner.invoke(app, ["pilot", "preflight", "--skip-ollama-probe"])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "Preflight falhou" in result.output


def test_preflight_json_fails_when_corpus_missing():
    result = runner.invoke(app, ["pilot", "preflight", "--json", "--skip-ollama-probe"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["is_ready"] is False
    names = {c["name"] for c in payload["checks"]}
    assert {"repertory", "embeddings_cache", "llm_availability"} <= names


def test_preflight_text_passes_when_everything_ready(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    _seed_chunks(db)

    cache = tmp_path / "hf" / "hub"
    snap = cache / "models--BAAI--bge-m3" / "snapshots" / "rev"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)

    result = runner.invoke(
        app,
        [
            "pilot",
            "preflight",
            "--out",
            str(tmp_path / "fresh"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Preflight OK" in result.output


def test_preflight_fixture_only_relaxes_corpus_requirement(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)
    result = runner.invoke(
        app,
        [
            "pilot",
            "preflight",
            "--fixture-only",
            "--skip-ollama-probe",
        ],
    )
    payload_lines = result.output
    assert "FAIL" not in payload_lines or "WARN" in payload_lines
    assert result.exit_code == 0, result.output


def test_preflight_cli_cloud_provider_can_satisfy_fixture_llm_check(monkeypatch):
    monkeypatch.setattr("juris.pilot.preflight.shutil.which", lambda command: f"/usr/bin/{command}")
    result = runner.invoke(
        app,
        [
            "pilot",
            "preflight",
            "--fixture-only",
            "--skip-ollama-probe",
            "--cli-cloud",
            "claude",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "CLI cloud claude disponível" in result.output


def test_preflight_json_payload_shape_when_passing(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    _seed_chunks(db)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)
    result = runner.invoke(
        app,
        ["pilot", "preflight", "--json", "--fixture-only"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["is_ready"] is True
    for c in payload["checks"]:
        assert set(c.keys()) >= {"name", "status", "message", "remediation", "details"}


def test_preflight_warns_about_legacy_db(tmp_path, monkeypatch):
    canonical = tmp_path / "rep.db"
    legacy = tmp_path / "data" / "repertory.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(canonical))
    _seed_chunks(canonical)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"legacy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)

    result = runner.invoke(app, ["pilot", "preflight", "--json"])
    payload = json.loads(result.output)
    assert payload["is_ready"] is True
    rep = next(c for c in payload["checks"] if c["name"] == "repertory")
    assert rep["status"] == "warn"
    assert "legacy_db_detected" in rep["details"]
