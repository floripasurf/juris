"""Public agent-distribution endpoint: serves the signed update manifest.

Integrity comes from the Ed25519 signature (see juris/agent/update.py), so this
route is intentionally public — no tenant dependency.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from juris.web.app import app


def test_agent_latest_is_public_and_serves_manifest(monkeypatch, tmp_path) -> None:
    (tmp_path / "agent-latest.json").write_text(
        json.dumps(
            {
                "version": "2026.7.4.1",
                "sha256": "a" * 64,
                "url": "https://x/y",
                "signature_alg": "ed25519",
                "signature": "Zg==",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_AGENT_DIST_DIR", str(tmp_path))
    r = TestClient(app).get("/api/agent/latest")  # sem X-API-Key → deve ser público
    assert r.status_code == 200
    assert r.json()["version"] == "2026.7.4.1"


def test_agent_latest_404_when_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_AGENT_DIST_DIR", str(tmp_path))
    assert TestClient(app).get("/api/agent/latest").status_code == 404
