"""Seam: the SPA must authenticate every /api call and gate the UI behind login.

The backend already rejects unauthenticated /api requests when tenants are
required (401 ``tenant_invalid``). Before the console goes online
(juris.blackcube.dev), the static SPA must hold up its side of that contract:
ship a login gate, send ``X-API-Key`` on every API call, and re-show the gate
on 401. These tests pin both sides of the seam.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from juris.web.app import app
from juris.web.auth import default_registry, hash_api_key

_INDEX_HTML = (
    Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")


@pytest.fixture
def required_tenant(monkeypatch, tmp_path):
    """One configured tenant with tenants required — the online-pilot posture."""
    tenants = tmp_path / "tenants.json"
    tenants.write_text(
        json.dumps({"escritorio-a": hash_api_key("key-a")}), encoding="utf-8"
    )
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    default_registry.cache_clear()
    yield {"X-API-Key": "key-a"}
    default_registry.cache_clear()


class TestBackendContract:
    """What the SPA relies on: structured 401 and an openly served login page."""

    def test_unauthenticated_api_call_returns_structured_401(self, required_tenant) -> None:
        client = TestClient(app)
        response = client.get("/api/workbench")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "tenant_invalid"

    def test_index_page_stays_open_so_login_can_render(self, required_tenant) -> None:
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "login-overlay" in response.text


class TestSpaLoginGate:
    """The static console ships the login gate and authenticated fetch wrapper."""

    def test_ships_login_overlay_with_key_input(self) -> None:
        assert 'id="login-overlay"' in _INDEX_HTML
        assert 'id="login-api-key"' in _INDEX_HTML

    def test_stores_key_in_session_storage_and_sends_x_api_key(self) -> None:
        assert "sessionStorage" in _INDEX_HTML
        assert "X-API-Key" in _INDEX_HTML

    def test_reopens_login_when_a_call_comes_back_401(self) -> None:
        assert re.search(r"status\s*===?\s*401", _INDEX_HTML), (
            "apiFetch deve detectar 401 e reabrir o login"
        )

    def test_hidden_modal_stays_hidden(self) -> None:
        """`.modal { display: flex }` vence o `[hidden]` do user-agent sem esta
        regra — sem ela, um modal vazio aparece em todo load do console."""
        assert re.search(r"\.modal\[hidden\]\s*\{[^}]*display:\s*none", _INDEX_HTML)

    def test_every_api_call_goes_through_api_fetch(self) -> None:
        """No raw fetch() may hit /api/* — new calls must inherit the auth header.

        The wrapper itself calls ``window.fetch`` so this stays a whole-file
        invariant: any bare ``fetch(`` is a regression.
        """
        raw_fetches = re.findall(r"(?<![\w.])fetch\s*\(", _INDEX_HTML)
        assert raw_fetches == [], (
            f"{len(raw_fetches)} chamada(s) fetch() sem X-API-Key — use apiFetch()."
        )
