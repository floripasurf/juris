"""Tests for the local Juris web UI."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from juris.web.app import app
from juris.web.demo_service import WebDemoArtifact, WebDemoRun

client = TestClient(app)


def test_index_renders_local_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Novo caso" in response.text
    assert "Gerar artefatos" in response.text
    assert "Meus processos" in response.text
    assert "Agenda de prazos" in response.text


def test_list_processos_endpoint_returns_views(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.processos_service import ProcessoView

    view = ProcessoView(
        numero_cnj="5082351-40.2017.8.13.0024",
        tribunal="tjmg",
        classe="Procedimento Comum",
        assunto="Cobrança",
        last_sync_at=None,
        prazos_pendentes=1,
        proximo_prazo=None,
        proximo_prazo_urgencia="alta",
    )
    monkeypatch.setattr(app_module, "list_processos", lambda: [view])

    response = client.get("/api/processos")

    assert response.status_code == 200
    body = response.json()
    assert body["processos"][0]["numero_cnj"] == "5082351-40.2017.8.13.0024"
    assert body["processos"][0]["prazos_pendentes"] == 1


def test_connect_endpoint_starts_async_job() -> None:
    response = client.post(
        "/api/connect",
        json={"cpf": "07671039632", "tribunal": "tjmg", "pin": "1234", "sync": True},
    )
    # 202 Accepted + a job id to poll (connect runs in the background).
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["job_id"]


def test_connect_endpoint_rejects_non_mtls_tribunal() -> None:
    response = client.post(
        "/api/connect",
        json={"cpf": "07671039632", "tribunal": "tjes", "pin": "1234"},
    )
    assert response.status_code == 400
    assert "mTLS" in response.json()["detail"]


def test_connect_job_get_unknown_returns_404() -> None:
    assert client.get("/api/connect/does-not-exist").status_code == 404


@pytest.mark.asyncio
async def test_connect_job_runner_records_result(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.jobs.connect import ConnectResult

    async def fake_run_connect(tribunal_cfg, cpf, senha, **kwargs):
        return ConnectResult(avisos_added=2, seed_added=3, total_tracked=5, first_time=True, sync=None)

    monkeypatch.setattr(app_module, "run_connect", fake_run_connect)
    payload = app_module.ConnectPayload(cpf="07671039632", tribunal="tjmg", pin="1234")
    app_module._CONNECT_JOBS["job-x"] = {"status": "running", "result": None, "error": None}

    await app_module._run_connect_job("job-x", object(), payload)

    job = app_module._CONNECT_JOBS["job-x"]
    assert job["status"] == "done"
    assert job["result"]["total_tracked"] == 5


def test_prazos_endpoint_returns_agenda(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.processos_service import PrazoView

    view = PrazoView(
        numero_cnj="5082351-40.2017.8.13.0024",
        data_limite=None,
        urgencia="alta",
        status="aberto",
        rule_nome="Contestação",
        tipo_acao="contestar",
    )
    monkeypatch.setattr(app_module, "list_prazos", lambda: [view])

    response = client.get("/api/prazos")

    assert response.status_code == 200
    assert response.json()["prazos"][0]["urgencia"] == "alta"


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
