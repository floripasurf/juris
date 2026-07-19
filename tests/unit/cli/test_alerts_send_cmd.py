"""`juris alerts send` — the single-tenant local call-site (Task 7 CLI coverage:
this is exactly the layer where the original bug — calling
send_pending_deadline_alerts() without db= — escaped unit coverage)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from juris.alerts.delivery import AlertEmailConfig
from juris.alerts.pending import PendingAlertDeliverySummary
from juris.cli.main import app
from juris.persistence.local_db import LocalDB

runner = CliRunner()


def _clear_alert_env(monkeypatch) -> None:
    for var in ("ALERT_SMTP_HOST", "ALERT_FROM_ADDRESS", "ALERT_TO_ADDRESSES", "JURIS_TENANTS_FILE"):
        monkeypatch.delenv(var, raising=False)


def test_alerts_send_reports_smtp_not_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path / "home"))
    _clear_alert_env(monkeypatch)

    result = runner.invoke(app, ["alerts", "send"])

    assert result.exit_code == 1
    assert "SMTP not configured" in result.output


def test_alerts_send_reports_no_recipients_distinct_from_smtp_not_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path / "home"))
    _clear_alert_env(monkeypatch)
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("ALERT_FROM_ADDRESS", "juris@example.test")
    tenants_path = tmp_path / "tenants.json"
    tenants_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants_path))

    result = runner.invoke(app, ["alerts", "send"])

    assert result.exit_code == 1
    assert "No alert recipients configured for tenant 'public'" in result.output
    assert "SMTP not configured" not in result.output


def test_alerts_send_passes_db_and_per_tenant_recipients(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path / "home"))
    _clear_alert_env(monkeypatch)
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("ALERT_FROM_ADDRESS", "juris@example.test")
    tenants_path = tmp_path / "tenants.json"
    tenants_path.write_text(
        json.dumps({"public": {"keys": {}, "alert_emails": ["adv@example.test"]}}), encoding="utf-8"
    )
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants_path))

    captured: dict[str, object] = {}

    async def fake_send(**kwargs: object) -> PendingAlertDeliverySummary:
        captured.update(kwargs)
        return PendingAlertDeliverySummary(smtp_configured=True, no_recipients=False, processos_checked=0)

    monkeypatch.setattr("juris.alerts.pending.send_pending_deadline_alerts", fake_send)

    result = runner.invoke(app, ["alerts", "send"])

    assert result.exit_code == 0, result.output
    assert isinstance(captured["db"], LocalDB)
    config = captured["config"]
    assert isinstance(config, AlertEmailConfig)
    assert config.to_addresses == ["adv@example.test"]
    assert "No processos in database" in result.output
