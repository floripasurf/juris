"""`juris overnight` CLI multi-tenant routing."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from juris.alerts.pending import PendingAlertDeliverySummary
from juris.cli.main import app
from juris.jobs.nightly import NightlyResult, NightlySummary
from juris.persistence.local_db import LocalDB
from juris.web.auth import Tenant, default_registry, tenant_db_path

runner = CliRunner()


def _summary_for(processo: dict[str, str]) -> NightlySummary:
    summary = NightlySummary()
    summary.results.append(
        NightlyResult(
            numero_cnj=processo["numero_cnj"],
            tribunal=processo["tribunal"],
            success=True,
        )
    )
    summary.finished_at = summary.started_at
    return summary


def test_overnight_all_tenants_runs_each_tenant_db(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    tenants_file = tmp_path / "tenants.json"
    tenants_file.write_text(
        json.dumps(
            {
                "escritorio-a": {
                    "keys": {"owner": {"hash": "key-a"}},
                    "parte_representada": "fazenda",
                },
                "escritorio-b": "key-b",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_HOME", str(home))
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants_file))
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    default_registry.cache_clear()

    db_a = LocalDB(tenant_db_path(Tenant("escritorio-a")))
    db_b = LocalDB(tenant_db_path(Tenant("escritorio-b")))
    db_a.set_tracked_list([{"numero_cnj": "0000001-00.2026.8.13.0001", "tribunal": "tjmg"}])
    db_b.set_tracked_list([{"numero_cnj": "0000002-00.2026.8.26.0001", "tribunal": "tjsp"}])

    captured: list[dict[str, object]] = []

    async def fake_run_nightly(processos, **kwargs):  # noqa: ANN001, ANN202
        captured.append(
            {
                "processos": processos,
                "db_path": kwargs["db"].path,
                "mni_service": kwargs["mni_service"],
                "cpf": kwargs["cpf"],
                "senha": kwargs["senha"],
                "parte_representada": kwargs["parte_representada"],
            }
        )
        return _summary_for(processos[0])

    monkeypatch.setattr("juris.jobs.nightly.run_nightly", fake_run_nightly)
    monkeypatch.setattr("juris.mni.factory.get_mni_read_service", lambda tenant_id: f"svc:{tenant_id}")

    result = runner.invoke(app, ["overnight", "--all-tenants", "--no-send-alerts"])

    assert result.exit_code == 0, result.output
    assert [call["mni_service"] for call in captured] == ["svc:escritorio-a", "svc:escritorio-b"]
    assert captured[0]["db_path"] == tenant_db_path(Tenant("escritorio-a"))
    assert captured[1]["db_path"] == tenant_db_path(Tenant("escritorio-b"))
    assert captured[0]["processos"] == [{"numero_cnj": "0000001-00.2026.8.13.0001", "tribunal": "tjmg"}]
    assert captured[1]["processos"] == [{"numero_cnj": "0000002-00.2026.8.26.0001", "tribunal": "tjsp"}]
    assert [call["parte_representada"] for call in captured] == ["fazenda", ""]
    assert "Nightly pipeline [escritorio-a]" in result.output
    assert "Nightly pipeline [escritorio-b]" in result.output
    default_registry.cache_clear()


def test_overnight_all_tenants_requires_configured_tenants(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tmp_path / "missing-tenants.json"))
    default_registry.cache_clear()

    result = runner.invoke(app, ["overnight", "--all-tenants", "--no-send-alerts"])

    assert result.exit_code == 1
    assert "JURIS_TENANTS_FILE" in result.output
    default_registry.cache_clear()


def test_tenant_prazo_parte_sets_and_clears_default(monkeypatch, tmp_path) -> None:
    tenants_file = tmp_path / "tenants.json"
    tenants_file.write_text(json.dumps({"escritorio-a": "key-a"}), encoding="utf-8")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants_file))
    default_registry.cache_clear()

    set_result = runner.invoke(
        app, ["tenant", "prazo-parte", "escritorio-a", "--set", "fazenda"]
    )
    assert set_result.exit_code == 0, set_result.output
    assert "escritorio-a: fazenda" in set_result.output
    stored = json.loads(tenants_file.read_text(encoding="utf-8"))
    assert stored["escritorio-a"]["parte_representada"] == "fazenda"
    assert stored["escritorio-a"]["keys"]["owner"]["hash"] == "key-a"

    clear_result = runner.invoke(
        app, ["tenant", "prazo-parte", "escritorio-a", "--set", "nenhuma"]
    )
    assert clear_result.exit_code == 0, clear_result.output
    stored = json.loads(tenants_file.read_text(encoding="utf-8"))
    assert "parte_representada" not in stored["escritorio-a"]
    default_registry.cache_clear()


def test_overnight_send_alerts_resolves_recipients_per_tenant(monkeypatch, tmp_path) -> None:
    """The layer where the original bug lived: each tenant must get ITS OWN
    recipient list, not the global one — one tenant here has alert_emails
    configured, the other doesn't, and delivery must diverge accordingly."""
    home = tmp_path / "home"
    tenants_file = tmp_path / "tenants.json"
    tenants_file.write_text(
        json.dumps(
            {
                "escritorio-a": {"keys": {"owner": {"hash": "key-a"}}, "alert_emails": ["adv-a@example.test"]},
                "escritorio-b": "key-b",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_HOME", str(home))
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants_file))
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("ALERT_FROM_ADDRESS", "juris@example.test")
    monkeypatch.delenv("ALERT_TO_ADDRESSES", raising=False)
    default_registry.cache_clear()

    db_a = LocalDB(tenant_db_path(Tenant("escritorio-a")))
    db_b = LocalDB(tenant_db_path(Tenant("escritorio-b")))
    db_a.set_tracked_list([{"numero_cnj": "0000001-00.2026.8.13.0001", "tribunal": "tjmg"}])
    db_b.set_tracked_list([{"numero_cnj": "0000002-00.2026.8.26.0001", "tribunal": "tjsp"}])

    async def fake_run_nightly(processos, **kwargs):  # noqa: ANN001, ANN202
        return _summary_for(processos[0])

    monkeypatch.setattr("juris.jobs.nightly.run_nightly", fake_run_nightly)
    monkeypatch.setattr("juris.mni.factory.get_mni_read_service", lambda tenant_id: f"svc:{tenant_id}")

    captured_recipients: list[list[str]] = []

    async def fake_send(*, db, config, **kwargs):  # noqa: ANN001, ANN202
        captured_recipients.append(list(config.to_addresses))
        return PendingAlertDeliverySummary(smtp_configured=True, no_recipients=not config.to_addresses)

    monkeypatch.setattr("juris.alerts.pending.send_pending_deadline_alerts", fake_send)

    result = runner.invoke(app, ["overnight", "--all-tenants"])

    assert result.exit_code == 0, result.output
    assert captured_recipients == [["adv-a@example.test"], []]
    assert "No alert recipients configured for tenant 'escritorio-b'" in result.output
    default_registry.cache_clear()
