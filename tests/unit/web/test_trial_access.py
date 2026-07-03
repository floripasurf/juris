"""Anonymous trial issuance and team API keys."""

from __future__ import annotations

import json

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
    assert "juris agent connect-relay wss://app.example/ws/agent-relay" in body["command"]
    assert trial["tenant_id"] in body["command"]
    after = json.loads(agents.read_text(encoding="utf-8"))[trial["tenant_id"]]["token"]
    assert after != before
    assert after in body["command"]
