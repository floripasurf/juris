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
    assert "renderEstrategia" in response.text  # strategy panel wired into the console
    assert "openProcessoDetail" in response.text  # per-process detail wired
    assert "renderReview" in response.text  # structured review panel wired
    assert "openAudit" in response.text  # audit viewer wired
    assert "showView" in response.text  # section navigation wired
    assert 'data-nav="acervo"' in response.text
    assert "escHtml" in response.text  # untrusted data escaped before innerHTML (XSS)


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
    monkeypatch.setattr(app_module, "list_processos", lambda db=None: [view])

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


def test_connect_jobs_are_bounded() -> None:
    app_module = importlib.import_module("juris.web.app")
    app_module._CONNECT_JOBS.clear()
    for i in range(app_module._MAX_CONNECT_JOBS + 10):
        app_module._evict_old_connect_jobs()
        app_module._CONNECT_JOBS[f"job-{i}"] = {"status": "done"}
    assert len(app_module._CONNECT_JOBS) <= app_module._MAX_CONNECT_JOBS


@pytest.mark.asyncio
async def test_connect_job_runner_records_result(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.jobs.connect import ConnectResult
    from juris.web.auth import Tenant

    captured: dict[str, object] = {}

    async def fake_run_connect(tribunal_cfg, cpf, senha, **kwargs):
        captured["db"] = kwargs.get("db")
        return ConnectResult(avisos_added=2, seed_added=3, total_tracked=5, first_time=True, sync=None)

    monkeypatch.setattr(app_module, "run_connect", fake_run_connect)
    monkeypatch.setattr(app_module, "_tenant_db", lambda tenant: f"db::{tenant.tenant_id}")
    payload = app_module.ConnectPayload(cpf="07671039632", tribunal="tjmg", pin="1234")
    app_module._CONNECT_JOBS["job-x"] = {"status": "running", "result": None, "error": None}

    await app_module._run_connect_job("job-x", object(), payload, Tenant("escritorio-a"))

    job = app_module._CONNECT_JOBS["job-x"]
    assert job["status"] == "done"
    assert job["result"]["total_tracked"] == 5
    assert job["tenant_id"] == "escritorio-a"  # job is owned by the tenant
    assert captured["db"] == "db::escritorio-a"  # writes scoped to the tenant's store


def test_audit_endpoint_returns_chain(monkeypatch) -> None:
    view = {"total": 2, "intact": True, "corrupted": [], "entries": [{"event_type": "draft"}]}
    import juris.web.audit_service as audit_service

    monkeypatch.setattr(audit_service, "audit_view", lambda path: view)
    response = client.get("/api/audit", params={"output_dir": "CASO-1"})
    assert response.status_code == 200
    assert response.json()["intact"] is True


def test_audit_endpoint_404_when_missing(monkeypatch) -> None:
    import juris.web.audit_service as audit_service

    def _raise(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(audit_service, "audit_view", _raise)
    assert client.get("/api/audit", params={"output_dir": "nope"}).status_code == 404


def test_audit_endpoint_rejects_path_traversal() -> None:
    assert client.get("/api/audit", params={"output_dir": "../../etc"}).status_code == 400


def test_processo_detail_endpoint_returns_detail(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.processos_service import MovimentoView, ProcessoDetailView

    detail = ProcessoDetailView(
        numero_cnj="A", tribunal="tjmg", classe="Apelação", assunto="Dano",
        orgao_julgador="3ª Câmara", valor_causa=1000.0, last_sync_at=None,
        movimentos=[MovimentoView(data_hora=None, descricao="Julgamento", tipo="m", categoria="decisao")],
        prazos=[],
    )
    monkeypatch.setattr(app_module, "get_processo_detail", lambda cnj, db=None: detail if cnj == "A" else None)

    ok = client.get("/api/processos/A")
    assert ok.status_code == 200
    assert ok.json()["movimentos"][0]["descricao"] == "Julgamento"
    assert client.get("/api/processos/MISSING").status_code == 404


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
    monkeypatch.setattr(app_module, "list_prazos", lambda db=None: [view])

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
            estrategia={"escolhida": {"tese": "forte", "confianca": "alta"}, "revisao_humana_obrigatoria": False},
            review={"counts": {"critical": 1}, "issues": [{"severity": "critical", "title": "x"}], "citations": []},
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
    assert body["estrategia"]["escolhida"]["tese"] == "forte"  # strategy surfaced to the console
    assert body["review"]["counts"]["critical"] == 1  # review surfaced to the console


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


def test_endpoints_enforce_api_key_when_tenants_configured(tmp_path, monkeypatch) -> None:
    import json

    from juris.web import auth

    app_module = importlib.import_module("juris.web.app")
    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": "secret-key"}), encoding="utf-8")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    auth.default_registry.cache_clear()  # pick up the configured registry
    monkeypatch.setattr(app_module, "list_prazos", lambda db=None: [])
    try:
        assert client.get("/api/prazos").status_code == 401  # no key → rejected
        ok = client.get("/api/prazos", headers={"X-API-Key": "secret-key"})
        assert ok.status_code == 200  # valid key → allowed
    finally:
        auth.default_registry.cache_clear()  # reset to open for other tests


def test_connect_job_hidden_from_non_owner() -> None:
    app_module = importlib.import_module("juris.web.app")
    # a job owned by escritorio-a is invisible to the public caller (open default)
    app_module._CONNECT_JOBS["job-y"] = {
        "status": "done", "result": {}, "error": None, "tenant_id": "escritorio-a",
    }
    assert client.get("/api/connect/job-y").status_code == 404


def test_localdb_is_cached_per_path(tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    path = str(tmp_path / "tenant.db")
    # same path → same LocalDB instance (engine/pool reused, not rebuilt per request)
    assert app_module._localdb_for_path(path) is app_module._localdb_for_path(path)


def test_ai_session_endpoint_returns_mode() -> None:
    body = client.get("/api/ai-session").json()
    assert body["mode"] in {"browser_session", "cloud_deid", "local"}
    assert "deidentify" in body


def test_index_renders_ai_session_badge() -> None:
    text = client.get("/").text
    assert 'id="ai-session"' in text
    assert "loadAiSession" in text


def test_connect_remote_mode_accepts_no_pin_or_senha(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.jobs.connect import ConnectResult

    async def fake_run_connect(*a, **k):
        return ConnectResult(avisos_added=0, seed_added=0, total_tracked=0, first_time=True, sync=None)

    monkeypatch.setattr(app_module, "run_connect", fake_run_connect)
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    # remote: the cloud must not carry pin/senha — they're omitted
    response = client.post("/api/connect", json={"cpf": "07671039632", "tribunal": "tjmg", "sync": False})
    assert response.status_code == 202, response.text


def test_connect_inprocess_mode_requires_pin(monkeypatch) -> None:
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    response = client.post("/api/connect", json={"cpf": "07671039632", "tribunal": "tjmg"})
    assert response.status_code == 400
    assert "PIN" in response.json()["detail"]
