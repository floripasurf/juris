"""Tests for `juris.pilot.preflight` — individual checks + aggregate report.

Each check is exercised against a controlled environment so the verdict is
deterministic. Network probes (Ollama) are stubbed via dependency injection.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from juris.pilot.preflight import (
    CheckStatus,
    check_corpus_depth,
    check_disk_space,
    check_embeddings_cache,
    check_llm_availability,
    check_ner_model,
    check_output_dir_clean,
    check_repertory,
    check_token,
    run_preflight,
)
from juris.repertory.readiness import (
    ENV_REPERTORY_PATH,
    LEGACY_REPERTORY_PATH,
)


def _seed_chunks(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
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
            "INSERT INTO chunks (chunk_id, source_id, source_type, text) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Pin canonical repertory path and HF cache to per-test temp dirs."""
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(tmp_path / "rep.db"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / LEGACY_REPERTORY_PATH
    legacy.parent.mkdir(parents=True, exist_ok=True)
    yield


# ---------------------------------------------------------------------------
# check_repertory
# ---------------------------------------------------------------------------


def test_check_repertory_fail_when_db_missing():
    result = check_repertory()
    assert result.status is CheckStatus.FAIL
    assert "não encontrado" in result.message
    assert result.remediation is not None


def test_check_repertory_fail_when_below_threshold(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    _seed_chunks(
        db,
        [
            ("c1", "s1", "STF", "x"),
            ("c2", "s1", "STF", "y"),
        ],
    )
    result = check_repertory()
    assert result.status is CheckStatus.FAIL
    assert "chunks insuficientes" in result.message


def test_check_repertory_warn_when_below_threshold_but_fixture_only(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    result = check_repertory(real_source_required=False)
    assert result.status is CheckStatus.WARN


def test_check_repertory_pass_when_thresholds_met(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    rows = [(f"c{i}", f"s{i % 5}", "STF" if i % 2 else "STJ", "x") for i in range(120)]
    _seed_chunks(db, rows)
    result = check_repertory()
    assert result.status is CheckStatus.PASS
    assert "120" in result.message


def test_check_repertory_warn_when_legacy_present_alongside_canonical(tmp_path, monkeypatch):
    canonical = tmp_path / "rep.db"
    legacy = tmp_path / "data" / "repertory.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(canonical))
    rows = [(f"c{i}", f"s{i % 5}", "STF" if i % 2 else "STJ", "x") for i in range(120)]
    _seed_chunks(canonical, rows)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"legacy")
    result = check_repertory()
    assert result.status is CheckStatus.WARN
    assert "banco legado" in (result.remediation or "")
    assert result.details["legacy_db_detected"] == str(legacy.resolve())


# ---------------------------------------------------------------------------
# check_corpus_depth
# ---------------------------------------------------------------------------


def test_check_corpus_depth_skips_when_corpus_missing():
    result = check_corpus_depth()
    assert result.status is CheckStatus.SKIP


def test_check_corpus_depth_warns_when_only_shallow_sources(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    rows = [(f"c{i}", f"s{i % 5}", "sumula", "x") for i in range(120)]
    _seed_chunks(db, rows)

    result = check_corpus_depth(min_full_text_chunks=1)

    assert result.status is CheckStatus.WARN
    assert "corpus público raso" in result.message


def test_check_corpus_depth_passes_with_full_text_sources(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    rows = [(f"c{i}", f"s{i % 5}", "acordao_publicado", "x") for i in range(30)]
    _seed_chunks(db, rows)

    result = check_corpus_depth(min_full_text_chunks=25)

    assert result.status is CheckStatus.PASS
    assert result.details["full_text_chunks"] == 30


# ---------------------------------------------------------------------------
# check_embeddings_cache
# ---------------------------------------------------------------------------


def test_check_embeddings_cache_warn_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    result = check_embeddings_cache(model_name="BAAI/bge-m3")
    assert result.status is CheckStatus.WARN
    assert "BAAI/bge-m3" in result.message
    assert "pré-aquecer" in (result.remediation or "")


def test_check_embeddings_cache_fails_when_required_in_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.delenv("JURIS_REQUIRE_EMBEDDINGS", raising=False)

    result = check_embeddings_cache(model_name="BAAI/bge-m3")

    assert result.status is CheckStatus.FAIL
    assert "falha fechado" in (result.remediation or "")


def test_check_embeddings_cache_explicit_override_can_relax_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("JURIS_REQUIRE_EMBEDDINGS", "0")

    result = check_embeddings_cache(model_name="BAAI/bge-m3")

    assert result.status is CheckStatus.WARN


def test_check_embeddings_cache_pass_when_snapshot_exists(tmp_path, monkeypatch):
    cache = tmp_path / "hf" / "hub"
    snap = cache / "models--BAAI--bge-m3" / "snapshots" / "deadbeef"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    result = check_embeddings_cache(model_name="BAAI/bge-m3")
    assert result.status is CheckStatus.PASS
    assert result.details["snapshots"] == 1


def test_check_embeddings_cache_warn_when_snapshot_dir_empty(tmp_path, monkeypatch):
    cache = tmp_path / "hf" / "hub"
    (cache / "models--BAAI--bge-m3" / "snapshots").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    result = check_embeddings_cache(model_name="BAAI/bge-m3")
    assert result.status is CheckStatus.WARN


# ---------------------------------------------------------------------------
# check_llm_availability
# ---------------------------------------------------------------------------


def test_check_llm_availability_fail_when_neither_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = check_llm_availability(probe_ollama=False)
    assert result.status is CheckStatus.FAIL
    assert "nenhum provedor" in result.message


def test_check_llm_availability_warn_when_only_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = check_llm_availability(probe_ollama=False)
    assert result.status is CheckStatus.WARN
    assert "Ollama indisponível" in result.message
    assert result.remediation is not None
    assert "casos com PII ficam bloqueados" in result.remediation


def test_check_llm_availability_warn_when_only_cli_cloud(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("juris.pilot.preflight.shutil.which", lambda command: f"/usr/bin/{command}")
    result = check_llm_availability(probe_ollama=False, cli_cloud_provider="claude")
    assert result.status is CheckStatus.WARN
    assert "CLI cloud claude disponível" in result.message
    assert result.details["cli_cloud_available"] is True
    assert result.remediation is not None
    assert "casos com PII ficam bloqueados" in result.remediation


def test_check_llm_availability_warn_when_only_ollama(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)
    result = check_llm_availability()
    assert result.status is CheckStatus.WARN
    assert "Ollama acessível" in result.message


def test_check_llm_availability_pass_when_both(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)
    result = check_llm_availability()
    assert result.status is CheckStatus.PASS


# ---------------------------------------------------------------------------
# check_output_dir_clean
# ---------------------------------------------------------------------------


def test_check_output_dir_skip_when_no_path():
    result = check_output_dir_clean(None)
    assert result.status is CheckStatus.SKIP


def test_check_output_dir_pass_when_missing(tmp_path):
    result = check_output_dir_clean(tmp_path / "nope")
    assert result.status is CheckStatus.PASS


def test_check_output_dir_pass_when_empty(tmp_path):
    out = tmp_path / "fresh-out"
    out.mkdir()
    result = check_output_dir_clean(out)
    assert result.status is CheckStatus.PASS


def test_check_output_dir_warn_when_existing_case_dirs(tmp_path):
    out = tmp_path / "stale-out"
    out.mkdir()
    (out / "0000000-00.0000.0.00.0000").mkdir()
    result = check_output_dir_clean(out)
    assert result.status is CheckStatus.WARN
    assert "auditoria" in (result.remediation or "")


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------


def test_check_disk_space_pass_with_normal_threshold(tmp_path):
    result = check_disk_space(tmp_path, min_free_mb=1)
    assert result.status is CheckStatus.PASS


def test_check_disk_space_warn_when_under_threshold(tmp_path):
    huge = 10**12
    result = check_disk_space(tmp_path, min_free_mb=huge)
    assert result.status is CheckStatus.WARN


# ---------------------------------------------------------------------------
# run_preflight aggregator
# ---------------------------------------------------------------------------


def test_run_preflight_aggregate_report_fail(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = run_preflight(probe_ollama=False)
    assert report.is_ready is False
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["repertory"] is CheckStatus.FAIL
    assert statuses["llm_availability"] is CheckStatus.FAIL


def test_run_preflight_aggregate_report_pass(tmp_path, monkeypatch):
    db = tmp_path / "rep.db"
    monkeypatch.setenv(ENV_REPERTORY_PATH, str(db))
    rows = [(f"c{i}", f"s{i % 5}", "STF" if i % 2 else "STJ", "x") for i in range(120)]
    _seed_chunks(db, rows)

    cache = tmp_path / "hf" / "hub"
    snap = cache / "models--BAAI--bge-m3" / "snapshots" / "rev"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("juris.pilot.preflight._ollama_reachable", lambda url, timeout=1.5: True)

    report = run_preflight(out_root=tmp_path / "fresh-out", probe_ollama=True)
    assert report.is_ready is True
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["repertory"] is CheckStatus.PASS
    assert statuses["embeddings_cache"] is CheckStatus.PASS
    assert statuses["llm_availability"] is CheckStatus.PASS
    assert statuses["output_dir"] is CheckStatus.PASS


def test_run_preflight_to_dict_shape(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = run_preflight(probe_ollama=False)
    payload = report.to_dict()
    assert set(payload) == {"is_ready", "has_warnings", "checks"}
    assert isinstance(payload["checks"], list)
    first = payload["checks"][0]
    assert set(first) >= {"name", "status", "message", "remediation", "details"}


class TestCheckToken:
    """Token A3 probe for the live MNI session (gated, no PIN needed)."""

    @staticmethod
    def _material(not_valid_after: str, label: str = "TOKEN CERTDATA"):
        return SimpleNamespace(token_label=label, not_valid_after=not_valid_after)

    def test_skip_when_not_probed(self) -> None:
        assert check_token(probe=False).status is CheckStatus.SKIP

    def test_pass_for_valid_cert(self) -> None:
        result = check_token(
            probe=True, reader=lambda: self._material("2099-01-01"), today=date(2026, 6, 25)
        )
        assert result.status is CheckStatus.PASS

    def test_warn_when_expiring_soon(self) -> None:
        result = check_token(
            probe=True, reader=lambda: self._material("2026-07-05"), today=date(2026, 6, 25)
        )
        assert result.status is CheckStatus.WARN

    def test_fail_for_expired_cert(self) -> None:
        result = check_token(
            probe=True, reader=lambda: self._material("2020-01-01"), today=date(2026, 6, 25)
        )
        assert result.status is CheckStatus.FAIL

    def test_fail_when_token_absent(self) -> None:
        def _raise() -> SimpleNamespace:
            raise RuntimeError("no token detected /var/private/pkcs11 token=abc pin=1234")

        result = check_token(probe=True, reader=_raise)

        assert result.status is CheckStatus.FAIL
        assert result.details == {"error": "token_unavailable"}
        dumped = json.dumps(result.to_dict())
        assert "/var/private/pkcs11" not in dumped
        assert "token=abc" not in dumped
        assert "pin=1234" not in dumped

    def test_run_preflight_skips_token_by_default(self) -> None:
        report = run_preflight(real_source_required=False, probe_ollama=False)
        token = next((c for c in report.checks if c.name == "token_a3"), None)
        assert token is not None
        assert token.status is CheckStatus.SKIP


class TestCheckNerModel:
    """LeNER-Br de-id model probe for the cloud/browser session."""

    def test_skip_when_not_probed(self) -> None:
        assert check_ner_model(probe=False).status is CheckStatus.SKIP

    def test_warn_when_model_missing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        result = check_ner_model(probe=True, model_name="acme/lenerbr")
        assert result.status is CheckStatus.WARN
        assert "acme/lenerbr" in result.message

    def test_pass_when_cached(self, tmp_path, monkeypatch) -> None:
        cache = tmp_path / "hf" / "hub"
        snap = cache / "models--acme--lenerbr" / "snapshots" / "deadbeef"
        snap.mkdir(parents=True)
        (snap / "config.json").write_text("{}")
        monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
        result = check_ner_model(probe=True, model_name="acme/lenerbr")
        assert result.status is CheckStatus.PASS

    def test_run_preflight_skips_ner_by_default(self) -> None:
        report = run_preflight(real_source_required=False, probe_ollama=False)
        ner = next((c for c in report.checks if c.name == "ner_model"), None)
        assert ner is not None
        assert ner.status is CheckStatus.SKIP
