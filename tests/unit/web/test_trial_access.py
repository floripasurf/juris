"""Anonymous trial issuance and team API keys."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from juris.web.app import app
from juris.web.auth import default_registry


@pytest.fixture
def trial_env(monkeypatch, tmp_path):
    tenants = tmp_path / "tenants.json"
    agents = tmp_path / "agents.json"
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "home" / "out"))
    monkeypatch.setenv("JURIS_TRIAL_RELAY_URL", "wss://app.example/ws/agent-relay")
    default_registry.cache_clear()
    yield tenants, agents
    default_registry.cache_clear()


def test_start_trial_creates_anonymous_30_day_access(trial_env) -> None:
    tenants, agents = trial_env
    client = TestClient(app)

    response = client.post("/api/trial/start")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tenant_id"].startswith("trial_")
    assert body["api_key"].startswith("causia_")
    assert body["trial_days"] == 30
    assert body["agent"]["relay_url"] == "wss://app.example/ws/agent-relay"
    assert body["agent"]["local_pairing"]["endpoint"] == "http://127.0.0.1:8765/pair-relay"
    assert body["agent"]["local_pairing"]["tenant_id"] == body["tenant_id"]
    assert body["agent"]["local_pairing"]["agent_token"]
    assert body["tenant_id"] in body["agent"]["command"]
    assert body["api_key"] not in tenants.read_text(encoding="utf-8")

    tenant_data = json.loads(tenants.read_text(encoding="utf-8"))
    agent_data = json.loads(agents.read_text(encoding="utf-8"))
    assert tenant_data[body["tenant_id"]]["kind"] == "trial"
    assert agent_data[body["tenant_id"]]["transport"] == "relay"

    authed = client.get("/api/workbench", headers={"X-API-Key": body["api_key"]})
    assert authed.status_code == 200, authed.text


def test_trial_relay_url_defaults_to_public_causia_domain(monkeypatch) -> None:
    from juris.web.trial_access import trial_relay_url

    monkeypatch.delenv("JURIS_TRIAL_RELAY_URL", raising=False)

    assert trial_relay_url() == "wss://causia.com.br/ws/agent-relay"


def test_access_key_endpoint_issues_team_key_for_same_tenant(trial_env) -> None:
    client = TestClient(app)
    trial = client.post("/api/trial/start").json()

    issued = client.post(
        "/api/access-keys",
        headers={"X-API-Key": trial["api_key"]},
        json={"label": "estagiário"},
    )

    assert issued.status_code == 201, issued.text
    key = issued.json()["api_key"]
    assert key.startswith("causia_")
    assert key != trial["api_key"]
    assert issued.json()["tenant_id"] == trial["tenant_id"]

    authed = client.get("/api/workbench", headers={"X-API-Key": key})
    assert authed.status_code == 200, authed.text

    summary = client.get("/api/access", headers={"X-API-Key": trial["api_key"]}).json()
    assert summary["trial"] is True
    assert any(item["label"] == "estagiário" for item in summary["keys"])


def test_agent_pairing_endpoint_rotates_relay_command(trial_env) -> None:
    _tenants, agents = trial_env
    client = TestClient(app)
    trial = client.post("/api/trial/start").json()
    before = json.loads(agents.read_text(encoding="utf-8"))[trial["tenant_id"]]["token"]

    response = client.post("/api/agent/pairing", headers={"X-API-Key": trial["api_key"]})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tenant_id"] == trial["tenant_id"]
    assert body["relay_url"] == "wss://app.example/ws/agent-relay"
    assert body["local_pairing"]["endpoint"] == "http://127.0.0.1:8765/pair-relay"
    assert body["local_pairing"]["tenant_id"] == trial["tenant_id"]
    assert "juris agent connect-relay wss://app.example/ws/agent-relay" in body["command"]
    assert trial["tenant_id"] in body["command"]
    after = json.loads(agents.read_text(encoding="utf-8"))[trial["tenant_id"]]["token"]
    assert after != before
    assert after in body["command"]


def test_start_trial_prunes_expired_trials_and_agent_bindings(trial_env) -> None:
    tenants, agents = trial_env
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tenants.write_text(
        json.dumps(
            {
                "trial_old": {
                    "kind": "trial",
                    "trial_expires_at": "2025-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "a" * 64}},
                },
                "trial_active": {
                    "kind": "trial",
                    "trial_expires_at": "2999-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "b" * 64}},
                },
            }
        ),
        encoding="utf-8",
    )
    agents.write_text(
        json.dumps({"trial_old": {"token": "old"}, "trial_active": {"token": "active"}}),
        encoding="utf-8",
    )

    from juris.web.trial_access import create_trial_access

    created = create_trial_access(tenants_path=tenants, agents_path=agents, now=now)

    tenant_data = json.loads(tenants.read_text(encoding="utf-8"))
    agent_data = json.loads(agents.read_text(encoding="utf-8"))
    assert "trial_old" not in tenant_data
    assert "trial_old" not in agent_data
    assert "trial_active" in tenant_data
    assert "trial_active" in agent_data
    assert created.tenant_id in tenant_data
    assert created.tenant_id in agent_data


def test_start_trial_records_pruned_trial_in_pending_erasure_ledger(trial_env) -> None:
    tenants, agents = trial_env
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tenants.write_text(
        json.dumps(
            {
                "trial_old": {
                    "kind": "trial",
                    "trial_expires_at": "2025-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "a" * 64}},
                },
            }
        ),
        encoding="utf-8",
    )

    from juris.web.trial_access import create_trial_access, read_pending_erasure

    create_trial_access(tenants_path=tenants, agents_path=agents, now=now)

    ledger = read_pending_erasure(tenants)
    assert set(ledger) == {"trial_old"}
    assert ledger["trial_old"]["trial_expires_at"] == "2025-01-01T00:00:00Z"
    assert ledger["trial_old"]["pruned_at"]


def test_sweep_expired_trials_prunes_and_enqueues_only_expired(tmp_path) -> None:
    tenants = tmp_path / "tenants.json"
    tenants.write_text(
        json.dumps(
            {
                "trial_old": {
                    "kind": "trial",
                    "trial_expires_at": "2025-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "a" * 64}},
                },
                "trial_active": {
                    "kind": "trial",
                    "trial_expires_at": "2999-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "b" * 64}},
                },
            }
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    from juris.web.trial_access import read_pending_erasure, sweep_expired_trials

    pruned = sweep_expired_trials(tenants_path=tenants, agents_path=None, now=now)

    assert set(pruned) == {"trial_old"}
    tenant_data = json.loads(tenants.read_text(encoding="utf-8"))
    assert "trial_old" not in tenant_data
    assert "trial_active" in tenant_data
    ledger = read_pending_erasure(tenants)
    assert set(ledger) == {"trial_old"}


def test_sweep_expired_trials_is_idempotent_and_never_loses_ledger_entries(tmp_path) -> None:
    tenants = tmp_path / "tenants.json"
    tenants.write_text(
        json.dumps(
            {
                "trial_old": {
                    "kind": "trial",
                    "trial_expires_at": "2025-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "a" * 64}},
                },
            }
        ),
        encoding="utf-8",
    )

    from juris.web.trial_access import read_pending_erasure, sweep_expired_trials

    first_now = datetime(2026, 1, 1, tzinfo=UTC)
    sweep_expired_trials(tenants_path=tenants, agents_path=None, now=first_now)
    first_ledger = read_pending_erasure(tenants)
    assert set(first_ledger) == {"trial_old"}
    first_pruned_at = first_ledger["trial_old"]["pruned_at"]

    # Simulate the same id being pruned a second time (e.g. re-added and expired
    # again): the ledger entry must not be duplicated or overwritten/lost.
    tenants.write_text(
        json.dumps(
            {
                "trial_old": {
                    "kind": "trial",
                    "trial_expires_at": "2025-06-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "a" * 64}},
                },
            }
        ),
        encoding="utf-8",
    )
    second_now = datetime(2026, 2, 1, tzinfo=UTC)
    pruned_again = sweep_expired_trials(tenants_path=tenants, agents_path=None, now=second_now)

    assert set(pruned_again) == {"trial_old"}
    second_ledger = read_pending_erasure(tenants)
    assert set(second_ledger) == {"trial_old"}
    assert second_ledger["trial_old"]["pruned_at"] == first_pruned_at


def test_is_tenant_active(tmp_path) -> None:
    tenants = tmp_path / "tenants.json"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tenants.write_text(
        json.dumps(
            {
                "trial_active": {"kind": "trial", "trial_expires_at": "2999-01-01T00:00:00Z", "keys": {}},
                "trial_expired": {"kind": "trial", "trial_expires_at": "2020-01-01T00:00:00Z", "keys": {}},
                "conta-legada": "sha256:" + "c" * 64,
            }
        ),
        encoding="utf-8",
    )

    from juris.web.trial_access import is_tenant_active

    assert is_tenant_active(tenants, "trial_active", now=now) is True
    assert is_tenant_active(tenants, "trial_expired", now=now) is False
    assert is_tenant_active(tenants, "conta-legada", now=now) is True
    assert is_tenant_active(tenants, "nao-existe", now=now) is False


def test_start_trial_enforces_active_trial_cap(trial_env, monkeypatch) -> None:
    tenants, agents = trial_env
    monkeypatch.setenv("JURIS_TRIAL_MAX_ACTIVE", "1")
    tenants.write_text(
        json.dumps(
            {
                "trial_active": {
                    "kind": "trial",
                    "trial_expires_at": "2999-01-01T00:00:00Z",
                    "keys": {"owner": {"hash": "sha256:" + "b" * 64}},
                }
            }
        ),
        encoding="utf-8",
    )
    agents.write_text(json.dumps({"trial_active": {"token": "active"}}), encoding="utf-8")

    client = TestClient(app)

    response = client.post("/api/trial/start")

    assert response.status_code == 429
    assert "Limite de testes" in response.json()["detail"]
    assert set(json.loads(tenants.read_text(encoding="utf-8"))) == {"trial_active"}
    assert set(json.loads(agents.read_text(encoding="utf-8"))) == {"trial_active"}
