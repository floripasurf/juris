"""Security hardening: CSP + headers, gated internal endpoints (S2, S4).

The console holds the tenant API key in sessionStorage, so any XSS = key theft.
CSP with per-script hashes (no 'unsafe-inline' on scripts) plus the standard
hardening headers close that class. And the internal config endpoints must not
answer to the open internet.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from juris.web.app import app
from juris.web.auth import default_registry, hash_api_key


@pytest.fixture
def required_tenant(monkeypatch, tmp_path):
    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": hash_api_key("key-a")}), encoding="utf-8")
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    default_registry.cache_clear()
    yield {"X-API-Key": "key-a"}
    default_registry.cache_clear()


class TestSecurityHeaders:
    def test_index_carries_csp_and_hardening_headers(self, required_tenant) -> None:
        r = TestClient(app).get("/")
        assert r.status_code == 200
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert "connect-src 'self' http://127.0.0.1:8765" in csp
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "permissions-policy" in r.headers

    def test_script_src_uses_hashes_not_unsafe_inline(self, required_tenant) -> None:
        csp = TestClient(app).get("/").headers.get("content-security-policy", "")
        script_directive = next(p for p in csp.split(";") if p.strip().startswith("script-src"))
        assert "'unsafe-inline'" not in script_directive
        assert "'sha256-" in script_directive

    def test_no_external_font_or_style_origin(self) -> None:
        html = (app and None) or __import__("pathlib").Path(
            "src/juris/web/static/index.html"
        ).read_text(encoding="utf-8")
        assert "fonts.googleapis.com" not in html
        assert "fonts.gstatic.com" not in html
        assert "/static/assets/fonts/fonts.css" in html


class TestGatedInternalEndpoints:
    def test_ai_session_requires_tenant(self, required_tenant) -> None:
        client = TestClient(app)
        assert client.get("/api/ai-session").status_code == 401
        assert client.get("/api/ai-session", headers=required_tenant).status_code == 200

    def test_agent_mode_requires_tenant(self, required_tenant) -> None:
        client = TestClient(app)
        assert client.get("/api/agent-mode").status_code == 401
        assert client.get("/api/agent-mode", headers=required_tenant).status_code == 200

    def test_health_stays_open(self, required_tenant) -> None:
        # readiness probe must answer unauthenticated
        assert TestClient(app).get("/health").status_code == 200
