"""Tests for `juris tenant` onboarding commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from juris.cli.main import app

runner = CliRunner()


def test_hash_key_outputs_sha256(monkeypatch) -> None:
    from juris.web.auth import hash_api_key

    result = runner.invoke(app, ["tenant", "hash-key", "minha-chave"])
    assert result.exit_code == 0
    assert hash_api_key("minha-chave") in result.output


def test_new_tenant_prints_raw_key_and_hash_entry() -> None:
    result = runner.invoke(app, ["tenant", "new", "escritorio-a"])
    assert result.exit_code == 0
    assert "sha256:" in result.output  # the stored hash
    assert '"escritorio-a":' in result.output


def test_new_tenant_rejects_reserved_public() -> None:
    result = runner.invoke(app, ["tenant", "new", "../escape"])
    assert result.exit_code == 2


def test_erase_data_defaults_to_dry_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "out"))
    (tmp_path / "home" / "tenants" / "escritorio-a").mkdir(parents=True)

    result = runner.invoke(app, ["tenant", "erase-data", "escritorio-a", "--json"])

    assert result.exit_code == 0
    body = json.loads(result.output)
    assert body["dry_run"] is True
    assert body["plan"]["confirmation_phrase"] == "ERASE-escritorio-a"
    targets = {target["path"] for target in body["plan"]["targets"]}
    assert str(tmp_path / "out" / "tenants" / "escritorio-a") in targets
    assert (tmp_path / "home" / "tenants" / "escritorio-a").exists()
