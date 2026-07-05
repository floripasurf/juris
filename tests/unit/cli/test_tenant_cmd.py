"""Tests for `juris tenant` onboarding commands."""

from __future__ import annotations

import json
from pathlib import Path

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


def _purge_env(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    out = tmp_path / "out"
    tenants_path = tmp_path / "tenants.json"
    monkeypatch.setenv("JURIS_HOME", str(home))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(out))
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants_path))
    monkeypatch.delenv("JURIS_AGENTS_FILE", raising=False)
    return home, out, tenants_path


def _seed_pending_tenant(home: Path, tmp_path: Path, tenant_id: str) -> None:
    (home / "tenants" / tenant_id).mkdir(parents=True)
    (home / "tenants" / tenant_id / "juris.db").write_text("data", encoding="utf-8")
    ledger_path = tmp_path / "pending-erasure.json"
    ledger_path.write_text(
        json.dumps(
            {tenant_id: {"trial_expires_at": "2020-01-01T00:00:00Z", "pruned_at": "2020-01-02T00:00:00Z"}}
        ),
        encoding="utf-8",
    )


def test_purge_expired_erases_pending_tenant_and_clears_ledger(tmp_path, monkeypatch) -> None:
    home, _out, tenants_path = _purge_env(monkeypatch, tmp_path)
    tenant_id = "trial_deadbeefcafe"
    _seed_pending_tenant(home, tmp_path, tenant_id)

    result = runner.invoke(app, ["tenant", "purge-expired", "--yes", "--json"])

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert [item["tenant_id"] for item in body["erased"]] == [tenant_id]
    assert body["failed"] == []
    assert not (home / "tenants" / tenant_id).exists()
    assert (home / "compliance-erasure.jsonl").exists()
    ledger_path = tmp_path / "pending-erasure.json"
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == {}


def test_purge_expired_leaves_id_pending_on_erasure_failure(tmp_path, monkeypatch) -> None:
    home, _out, tenants_path = _purge_env(monkeypatch, tmp_path)
    tenant_id = "trial_willfail0001"
    _seed_pending_tenant(home, tmp_path, tenant_id)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disco cheio (simulado)")

    monkeypatch.setattr("juris.ops.erasure.execute_tenant_erasure", _boom)

    result = runner.invoke(app, ["tenant", "purge-expired", "--yes", "--json"])

    assert result.exit_code != 0
    body = json.loads(result.output)
    assert [item["tenant_id"] for item in body["failed"]] == [tenant_id]
    assert body["erased"] == []
    assert (home / "tenants" / tenant_id).exists()
    ledger_path = tmp_path / "pending-erasure.json"
    assert tenant_id in json.loads(ledger_path.read_text(encoding="utf-8"))


def test_purge_expired_never_erases_tenant_still_active_in_tenants_json(tmp_path, monkeypatch) -> None:
    home, _out, tenants_path = _purge_env(monkeypatch, tmp_path)
    tenant_id = "trial_stillactive0"
    _seed_pending_tenant(home, tmp_path, tenant_id)
    tenants_path.write_text(
        json.dumps({tenant_id: {"kind": "trial", "trial_expires_at": "2999-01-01T00:00:00Z", "keys": {}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["tenant", "purge-expired", "--yes", "--json"])

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert [item["tenant_id"] for item in body["skipped"]] == [tenant_id]
    assert body["erased"] == []
    assert (home / "tenants" / tenant_id).exists()


def test_purge_expired_dry_run_changes_nothing_on_disk(tmp_path, monkeypatch) -> None:
    home, _out, tenants_path = _purge_env(monkeypatch, tmp_path)
    tenant_id = "trial_dryrun00000"
    _seed_pending_tenant(home, tmp_path, tenant_id)
    ledger_path = tmp_path / "pending-erasure.json"
    ledger_before = ledger_path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["tenant", "purge-expired", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["dry_run"] is True
    assert [item["tenant_id"] for item in body["erased"]] == [tenant_id]
    assert (home / "tenants" / tenant_id).exists()
    assert not (home / "compliance-erasure.jsonl").exists()
    assert ledger_path.read_text(encoding="utf-8") == ledger_before
    assert not tenants_path.exists()


def test_purge_expired_exits_zero_with_nothing_pending(tmp_path, monkeypatch) -> None:
    _purge_env(monkeypatch, tmp_path)

    result = runner.invoke(app, ["tenant", "purge-expired", "--yes", "--json"])

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["erased"] == body["skipped"] == body["failed"] == []
