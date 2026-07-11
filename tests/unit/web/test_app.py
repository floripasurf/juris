"""Tests for the local Juris web UI."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from juris.web.app import app
from juris.web.demo_service import WebDemoArtifact, WebDemoRun

client = TestClient(app)


def test_index_renders_local_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Novo caso" in response.text
    assert "Gerar artefatos" in response.text


def test_create_demo_run_returns_artifact_previews(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")

    async def fake_execute(_request):
        return WebDemoRun(
            succeeded=True,
            degraded=False,
            degradation_reason="",
            errors=(),
            duration_seconds=1.2,
            output_dir="juris-out/DEMO-0001234-56.2026.8.13.0001",
            artifacts=(
                WebDemoArtifact(
                    name="rascunho-pesquisa.md",
                    path="juris-out/DEMO-0001234-56.2026.8.13.0001/rascunho-pesquisa.md",
                    sha256="abc123",
                    preview="# Rascunho",
                ),
            ),
        )

    monkeypatch.setattr(app_module, "execute_demo_run", fake_execute)

    response = client.post(
        "/api/demo-runs",
        json={
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "tipo": "contestacao",
            "source": "fixture",
            "modo": "rascunho-pesquisa",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] is True
    assert body["artifacts"][0]["name"] == "rascunho-pesquisa.md"
    assert body["artifacts"][0]["preview"] == "# Rascunho"


def test_create_demo_run_executes_real_service_path(monkeypatch, tmp_path: Path) -> None:
    demo_service = importlib.import_module("juris.web.demo_service")

    async def fake_run_demo(_request, **kwargs):
        return SimpleNamespace(
            succeeded=True,
            degraded=False,
            degradation_reason="",
            errors=[],
            duration_seconds=0.4,
            out_dir=kwargs["out_dir"],
        )

    def fake_write_artifacts(result):
        artifact_path = result.out_dir / "rascunho-pesquisa.md"
        artifact_path.write_text("# Rascunho real\n\nConteúdo gerado.", encoding="utf-8")
        return {"rascunho-pesquisa.md": "sha-real"}

    monkeypatch.setattr(demo_service, "_build_llm", lambda *, use_cloud: object())
    monkeypatch.setattr(demo_service, "_build_repertory", lambda _path: object())
    monkeypatch.setattr(demo_service, "load_processo", lambda *args, **kwargs: object())
    monkeypatch.setattr(demo_service, "run_demo", fake_run_demo)
    monkeypatch.setattr(demo_service, "write_artifacts", fake_write_artifacts)

    response = client.post(
        "/api/demo-runs",
        json={
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "tipo": "contestacao",
            "source": "fixture",
            "modo": "rascunho-pesquisa",
            "out_root": str(tmp_path),
            "skip_review": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["succeeded"] is True
    assert body["artifacts"][0]["name"] == "rascunho-pesquisa.md"
    assert body["artifacts"][0]["preview"].startswith("# Rascunho real")


def test_create_demo_run_rejects_non_local_host() -> None:
    response = client.post(
        "/api/demo-runs",
        headers={"host": "public.example.com"},
        json={
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "tipo": "contestacao",
            "source": "fixture",
            "modo": "rascunho-pesquisa",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Juris web local só aceita requests locais"
