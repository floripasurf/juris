"""Tests for `juris tenant` onboarding commands."""

from __future__ import annotations

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
