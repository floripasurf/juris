"""Tests for `juris doctor` (production readiness)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from juris.cli.main import app

runner = CliRunner()


def test_doctor_exits_nonzero_when_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JURIS_REQUIRE_TENANTS", raising=False)
    monkeypatch.delenv("JURIS_TENANTS_FILE", raising=False)
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "NÃO pronto" in result.output


def test_doctor_passes_with_full_config(monkeypatch, tmp_path) -> None:
    from juris.web.auth import hash_api_key

    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": hash_api_key("k")}), encoding="utf-8")
    import os

    os.chmod(tenants, 0o600)
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_AGENT_MODE", "inprocess")
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "out"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Pronto para produção" in result.output
