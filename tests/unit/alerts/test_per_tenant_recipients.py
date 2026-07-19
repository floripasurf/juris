"""Per-tenant deadline-alert recipients (Task 7): helper, legacy migration,
config override, required ``db``, and distinct no-recipients/no-SMTP states.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from juris.alerts.delivery import AlertEmailConfig
from juris.alerts.pending import (
    alert_email_config_from_settings,
    alert_recipients_for_tenant,
    send_pending_deadline_alerts,
)
from juris.config import Settings
from juris.persistence.local_db import LocalDB
from juris.web.auth import TenantRegistry, hash_api_key
from juris.web.trial_access import add_alert_email, alert_emails_for_tenant


def run_async(coro):
    return asyncio.run(coro)


def _write_tenants(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "tenants.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# (a) helper lê lista do tenants.json de objeto.
def test_alert_emails_for_tenant_reads_list_from_structured_entry(tmp_path) -> None:
    path = _write_tenants(
        tmp_path,
        {
            "escritorio-a": {
                "kind": "account",
                "keys": {},
                "alert_emails": ["adv@escritorio-a.test", "socia@escritorio-a.test"],
            }
        },
    )

    assert alert_emails_for_tenant("escritorio-a", path=path) == [
        "adv@escritorio-a.test",
        "socia@escritorio-a.test",
    ]


# (b) entrada string legada → [] sem exceção.
def test_alert_emails_for_tenant_legacy_string_entry_returns_empty_without_crash(tmp_path) -> None:
    path = _write_tenants(tmp_path, {"escritorio-piloto": "sha256:" + "a" * 64})

    assert alert_emails_for_tenant("escritorio-piloto", path=path) == []


def test_alert_emails_for_tenant_missing_tenant_returns_empty(tmp_path) -> None:
    path = _write_tenants(tmp_path, {})

    assert alert_emails_for_tenant("nao-existe", path=path) == []


def test_alert_emails_for_tenant_drops_invalid_addresses_without_logging_raw_email(tmp_path) -> None:
    path = _write_tenants(
        tmp_path,
        {
            "escritorio-a": {
                "kind": "account",
                "keys": {},
                "alert_emails": ["valida@escritorio-a.test", "invalido-sem-arroba"],
            }
        },
    )

    with structlog.testing.capture_logs() as logs:
        result = alert_emails_for_tenant("escritorio-a", path=path)

    assert result == ["valida@escritorio-a.test"]
    warnings = [event for event in logs if event.get("event") == "alert_email_invalido"]
    assert len(warnings) == 1
    assert warnings[0]["tenant_id"] == "escritorio-a"
    assert warnings[0]["dominio"] == "malformado"
    assert "invalido-sem-arroba" not in str(logs)


# (c) --add sobre entrada legada migra para objeto PRESERVANDO o hash da chave;
# autenticação com a chave antiga continua válida.
def test_add_alert_email_migrates_legacy_string_entry_preserving_key_hash(tmp_path) -> None:
    raw_key = "causia_raw_key_1234567890abcdef"
    key_hash = hash_api_key(raw_key)
    path = _write_tenants(tmp_path, {"escritorio-piloto": key_hash})

    emails = add_alert_email("escritorio-piloto", "adv@escritorio-piloto.test", tenants_path=path)

    assert emails == ["adv@escritorio-piloto.test"]
    stored = json.loads(path.read_text(encoding="utf-8"))["escritorio-piloto"]
    assert isinstance(stored, dict)
    assert stored["keys"]["owner"]["hash"] == key_hash

    registry = TenantRegistry.from_file(path)
    tenant = registry.authenticate(raw_key)
    assert tenant is not None
    assert tenant.tenant_id == "escritorio-piloto"


def test_remove_alert_email_drops_address(tmp_path) -> None:
    path = _write_tenants(
        tmp_path,
        {
            "escritorio-a": {
                "kind": "account",
                "keys": {},
                "alert_emails": ["a@escritorio-a.test", "b@escritorio-a.test"],
            }
        },
    )

    emails = remove_alert_email_helper(path, "a@escritorio-a.test")

    assert emails == ["b@escritorio-a.test"]


def remove_alert_email_helper(path: Path, email: str) -> list[str]:
    from juris.web.trial_access import remove_alert_email

    return remove_alert_email("escritorio-a", email, tenants_path=path)


def test_add_alert_email_unknown_tenant_raises_key_error(tmp_path) -> None:
    import pytest

    path = _write_tenants(tmp_path, {})
    with pytest.raises(KeyError):
        add_alert_email("nao-existe", "x@example.test", tenants_path=path)


# (d) to_addresses=[...] ignora o global.
def test_alert_email_config_from_settings_to_addresses_override_ignores_global() -> None:
    settings = Settings(
        _env_file=None,
        alert_smtp_host="smtp.example.test",
        alert_from_address="juris@example.test",
        alert_to_addresses="global@example.test",
    )

    config = alert_email_config_from_settings(settings, to_addresses=["tenant@escritorio-a.test"])

    assert config.to_addresses == ["tenant@escritorio-a.test"]


def test_alert_email_config_from_settings_defaults_to_global_when_no_override() -> None:
    settings = Settings(_env_file=None, alert_to_addresses="global@example.test, outro@example.test")

    config = alert_email_config_from_settings(settings)

    assert config.to_addresses == ["global@example.test", "outro@example.test"]


# (e) chamada sem db → TypeError.
def test_send_pending_deadline_alerts_without_db_raises_type_error() -> None:
    import pytest

    with pytest.raises(TypeError):
        send_pending_deadline_alerts()  # type: ignore[call-arg]


# (f) summary distingue no_recipients de smtp_configured.
def test_summary_distinguishes_no_recipients_from_smtp_not_configured(tmp_path) -> None:
    db = LocalDB(tmp_path / "alerts.db")

    no_smtp = run_async(
        send_pending_deadline_alerts(
            db=db,
            config=AlertEmailConfig(smtp_host="", from_address="", to_addresses=["a@b.test"]),
        )
    )
    assert no_smtp.smtp_configured is False
    assert no_smtp.no_recipients is False

    no_recipients = run_async(
        send_pending_deadline_alerts(
            db=db,
            config=AlertEmailConfig(
                smtp_host="smtp.example.test", from_address="juris@example.test", to_addresses=[]
            ),
        )
    )
    assert no_recipients.smtp_configured is True
    assert no_recipients.no_recipients is True


# alert_recipients_for_tenant: fallback ao global SOMENTE para escritorio-piloto.
def test_alert_recipients_for_tenant_prefers_configured_tenant_list(tmp_path) -> None:
    path = _write_tenants(
        tmp_path,
        {
            "escritorio-piloto": {
                "kind": "account",
                "keys": {},
                "alert_emails": ["tenant@escritorio-piloto.test"],
            }
        },
    )
    settings = Settings(_env_file=None, alert_to_addresses="global@example.test")

    result = alert_recipients_for_tenant("escritorio-piloto", path=path, settings=settings)

    assert result == ["tenant@escritorio-piloto.test"]


def test_alert_recipients_for_tenant_falls_back_to_global_only_for_pilot(tmp_path) -> None:
    path = _write_tenants(tmp_path, {})
    settings = Settings(_env_file=None, alert_to_addresses="global@example.test")

    assert alert_recipients_for_tenant("escritorio-piloto", path=path, settings=settings) == [
        "global@example.test"
    ]
    assert alert_recipients_for_tenant("outro-escritorio", path=path, settings=settings) == []
