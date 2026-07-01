"""Tests for the local Juris web UI."""

from __future__ import annotations

import hashlib
import importlib
import json
from datetime import date
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
    assert "Mesa de trabalho" in response.text
    assert "Gerar artefatos" in response.text
    assert "Meus processos" in response.text
    assert "Agenda de prazos" in response.text
    assert "renderEstrategia" in response.text  # strategy panel wired into the console
    assert "openProcessoDetail" in response.text  # per-process detail wired
    assert "renderReview" in response.text  # structured review panel wired
    assert "openAudit" in response.text  # audit viewer wired
    assert "showView" in response.text  # section navigation wired
    assert 'data-nav="acervo"' in response.text
    assert 'data-nav="mesa"' in response.text
    assert 'data-nav="protocolo"' in response.text
    assert "renderWorkbench" in response.text
    assert "/api/workbench" in response.text
    assert "Prazos críticos" in response.text
    assert "runMeta" in response.text
    assert "reviewSummary" in response.text
    assert "caseMeta" in response.text
    assert "caseActions" in response.text
    assert "processos-filter" in response.text
    assert "filteredProcessos" in response.text
    assert "prazos-urgency" in response.text
    assert "filteredPrazos" in response.text
    assert "Piloto instrumentado" in response.text
    assert "pilot-form" in response.text
    assert "/api/pilot-feedback" in response.text
    assert "/api/pilot-feedback/summary" in response.text
    assert "pilot-export-md" in response.text
    assert "renderPilotFeedback" in response.text
    assert "renderPilotSummary" in response.text
    assert "Fila de corpus" in response.text
    assert "/api/corpus/candidates" in response.text
    assert "/api/corpus/coverage" in response.text
    assert "renderCorpusCoverage" in response.text
    assert "/api/pilot-feedback/comparison" in response.text
    assert "renderPilotComparison" in response.text
    assert "Protocolo controlado" in response.text
    assert "/api/filing/status" in response.text
    assert "/api/filing/artifacts" in response.text
    assert "/api/filing/artifacts/content" in response.text
    assert "/api/filing/pending/recovery" in response.text
    assert "/api/filing/pending/archive" in response.text
    assert "/api/filing/dry-run" in response.text
    assert "/api/filing/submit" in response.text
    assert "loadFilingArtifacts" in response.text
    assert "renderFilingResult" in response.text
    assert "Cadeia de custódia" in response.text
    assert "Lacunas de prova antes da minuta" in response.text
    assert "Tom da minuta" in response.text
    assert "apiErrorMessage" in response.text
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


def test_connect_jobs_are_bounded(tmp_path) -> None:
    from juris.web.connect_jobs import ConnectJobStore

    store = ConnectJobStore(tmp_path / "jobs.db")
    for i in range(15):
        store.create(f"job-{i}", "t")
    store.evict_old(max_jobs=5)
    survivors = sum(1 for i in range(15) if store.get(f"job-{i}") is not None)
    assert survivors <= 5


@pytest.mark.asyncio
async def test_connect_job_runner_records_result(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.jobs.connect import ConnectResult
    from juris.web.auth import Tenant
    from juris.web.connect_jobs import ConnectJobStore

    store = ConnectJobStore(tmp_path / "jobs.db")
    captured: dict[str, object] = {}

    async def fake_run_connect(tribunal_cfg, cpf, senha, **kwargs):
        captured["db"] = kwargs.get("db")
        return ConnectResult(avisos_added=2, seed_added=3, total_tracked=5, first_time=True, sync=None)

    monkeypatch.setattr(app_module, "run_connect", fake_run_connect)
    monkeypatch.setattr(app_module, "_tenant_db", lambda tenant: f"db::{tenant.tenant_id}")
    monkeypatch.setattr(app_module, "_connect_job_store", lambda: store)
    payload = app_module.ConnectPayload(cpf="07671039632", tribunal="tjmg", pin="1234")
    store.create("job-x", "escritorio-a")

    await app_module._run_connect_job("job-x", object(), payload, Tenant("escritorio-a"))

    job = store.get("job-x")
    assert job["status"] == "done"
    assert job["result"]["total_tracked"] == 5
    assert job["tenant_id"] == "escritorio-a"  # job is owned by the tenant
    assert captured["db"] == "db::escritorio-a"  # writes scoped to the tenant's store


@pytest.mark.asyncio
async def test_connect_job_runner_sanitizes_internal_errors(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.auth import Tenant
    from juris.web.connect_jobs import ConnectJobStore

    store = ConnectJobStore(tmp_path / "jobs.db")

    async def fake_run_connect(*_args, **_kwargs):
        raise RuntimeError("mTLS /var/private/cert token=abc pin=1234")

    monkeypatch.setattr(app_module, "run_connect", fake_run_connect)
    monkeypatch.setattr(app_module, "_tenant_db", lambda tenant: f"db::{tenant.tenant_id}")
    monkeypatch.setattr(app_module, "_connect_job_store", lambda: store)
    payload = app_module.ConnectPayload(cpf="07671039632", tribunal="tjmg", pin="1234")
    store.create("job-secret", "escritorio-a")

    await app_module._run_connect_job("job-secret", object(), payload, Tenant("escritorio-a"))

    job = store.get("job-secret")
    assert job["status"] == "error"
    assert "Falha operacional" in job["error"]
    assert "token=abc" not in job["error"]
    assert "pin=1234" not in job["error"]
    assert "/var/private/cert" not in job["error"]


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


def _filing_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "numero_cnj": "0001234-56.2026.8.13.0001",
        "tribunal": "tjmg",
        "tipo_documento": "manifestacao",
        "tipo_peticao": "manifestacao",
        "draft_markdown": "# Petição\n\nTexto revisado.",
        "cpf": "07671039632",
        "senha": "senha",
        "pin": "1234",
        "review_confirmed": True,
        "consent": True,
    }
    payload.update(overrides)
    return payload


class _FakeFilingService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str | None]] = []

    async def file(self, request, *, pin=None):
        from juris.signing.filing import ChainOfCustody, FilingResult

        self.calls.append((request, pin))
        preflight = SimpleNamespace(
            passed=True,
            prazo_status=SimpleNamespace(value="unknown"),
            checks=[
                SimpleNamespace(
                    name="pdf_valid",
                    passed=True,
                    severity="blocker",
                    message="PDF válido",
                    retryable=False,
                )
            ],
        )
        chain = None
        receipt = None
        if not request.dry_run:
            from juris.mni.operations.peticionamento import FilingReceipt

            receipt = FilingReceipt(sucesso=True, mensagem="ok", protocolo="PROT-1", numero_processo=request.numero_cnj)
            chain = ChainOfCustody("pdf", "signed", "payload", "receipt")
        return FilingResult(
            success=True,
            receipt=receipt,
            signing_result=None,
            preflight=preflight,
            audit_entry_ids=["audit-1"],
            chain_of_custody=chain,
        )


class _FailingFilingService:
    async def file(self, request, *, pin=None):
        del request, pin
        raise RuntimeError("falha interna em /var/private/juris-token com token=abc123 e pin=1234")


def test_filing_status_endpoint(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))  # public tenant → <home>/filings
    (tmp_path / "filings" / "cnj" / "20260630_pending").mkdir(parents=True)

    response = client.get("/api/filing/status")

    assert response.status_code == 200
    assert response.json()["pending"][0]["receipt_id"] == "20260630_pending"
    assert str(tmp_path) not in response.text
    assert "filing_root" not in response.text
    assert '"path"' not in response.text


def test_filing_pending_recovery_and_archive_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))  # public tenant → <home>/filings
    pending = tmp_path / "filings" / "cnj" / "20260630_pending"
    pending.mkdir(parents=True)
    (pending / "signed.pdf").write_bytes(b"%PDF signed")
    (pending / "hashes.json").write_text(json.dumps({"signed_pdf_hash": "signed"}), encoding="utf-8")
    key = "cnj/20260630_pending"

    recovery = client.post("/api/filing/pending/recovery", json={"pending_key": key})
    blocked = client.post(
        "/api/filing/pending/archive",
        json={"pending_key": key, "reason": "conferido no portal", "confirm_manual_resolution": False},
    )
    archived = client.post(
        "/api/filing/pending/archive",
        json={"pending_key": key, "reason": "conferido no portal", "confirm_manual_resolution": True},
    )

    assert recovery.status_code == 200
    assert recovery.json()["safe_to_retry"] is False
    assert str(tmp_path) not in recovery.text
    assert blocked.status_code == 400
    assert "confirmação" in blocked.json()["detail"]
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert archived.json()["archived_key"] == "cnj/20260630_manual_resolution"
    assert str(tmp_path) not in archived.text
    assert client.get("/api/filing/status").json()["pending"] == []


def test_filing_artifact_endpoints_are_confined(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    draft = "# Minuta pronta"
    digest = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    (case_dir / "draft.md").write_text(draft, encoding="utf-8")
    (case_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "finished_at": "2026-06-30T12:00:00",
                "output_mode": "minuta-sugerida",
                "request": {"numero_cnj": "0001234-56.2026.8.13.0001", "tribunal": "tjmg"},
                "draft": {"grounding_status": "verified"},
                "artifacts": [{"name": "draft.md", "sha256": digest}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "_out_root", lambda: tmp_path)

    listed = client.get("/api/filing/artifacts")
    content = client.post(
        "/api/filing/artifacts/content",
        json={"output_dir": str(case_dir), "artifact_name": "draft.md"},
    )
    traversal = client.post(
        "/api/filing/artifacts/content",
        json={"output_dir": "../", "artifact_name": "draft.md"},
    )

    assert listed.status_code == 200
    assert listed.json()["artifacts"][0]["artifact_name"] == "draft.md"
    assert listed.json()["artifacts"][0]["output_dir"] == "CASE-1"
    assert listed.json()["artifacts"][0]["sha256_verified"] is True
    assert str(tmp_path) not in listed.text
    assert content.status_code == 200
    assert content.json()["content"] == "# Minuta pronta"
    assert content.json()["output_dir"] == "CASE-1"
    assert content.json()["sha256"] == digest
    assert str(tmp_path) not in content.text
    assert traversal.status_code == 400


def test_filing_dry_run_uses_service_without_consent_requirement(monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    service = _FakeFilingService()
    monkeypatch.setattr(filing_service, "get_filing_service", lambda tenant_id="public", **kwargs: service)

    response = client.post("/api/filing/dry-run", json=_filing_payload(consent=False, review_confirmed=False))

    assert response.status_code == 200, response.text
    assert response.json()["preflight"]["checks"][0]["name"] == "pdf_valid"
    request, pin = service.calls[0]
    assert request.dry_run is True
    assert pin == "1234"


def test_filing_dry_run_rejects_excessive_draft() -> None:
    app_module = importlib.import_module("juris.web.app")

    response = client.post(
        "/api/filing/dry-run",
        json=_filing_payload(
            consent=False,
            review_confirmed=False,
            draft_markdown="x" * (app_module._MAX_DRAFT_MARKDOWN + 1),
        ),
    )

    assert response.status_code == 422


def test_filing_submit_requires_review_and_consent() -> None:
    without_review = client.post("/api/filing/submit", json=_filing_payload(review_confirmed=False))
    without_consent = client.post("/api/filing/submit", json=_filing_payload(consent=False))

    assert without_review.status_code == 400
    assert "revisão" in without_review.json()["detail"]
    assert without_consent.status_code == 400
    assert "Consentimento" in without_consent.json()["detail"]


def test_filing_submit_returns_chain_of_custody(monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    service = _FakeFilingService()
    monkeypatch.setattr(filing_service, "get_filing_service", lambda tenant_id="public", **kwargs: service)

    response = client.post("/api/filing/submit", json=_filing_payload())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["receipt"]["protocolo"] == "PROT-1"
    assert body["chain_of_custody"] == {
        "pdf_hash": "pdf",
        "signed_pdf_hash": "signed",
        "submitted_payload_hash": "payload",
        "receipt_hash": "receipt",
    }


def test_filing_remote_mode_does_not_require_or_forward_secrets(monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    service = _FakeFilingService()
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    monkeypatch.setattr(filing_service, "get_filing_service", lambda tenant_id="public", **kwargs: service)

    response = client.post(
        "/api/filing/dry-run",
        json=_filing_payload(cpf=None, senha=None, pin=None, consent=False, review_confirmed=False),
    )

    assert response.status_code == 200, response.text
    request, pin = service.calls[0]
    assert request.cpf == ""
    assert request.senha == ""
    assert pin is None


def test_filing_errors_are_sanitized(monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    monkeypatch.setattr(
        filing_service,
        "get_filing_service",
        lambda tenant_id="public", **kwargs: _FailingFilingService(),
    )

    response = client.post("/api/filing/dry-run", json=_filing_payload(consent=False, review_confirmed=False))

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "filing_failed"
    assert "Falha operacional" in response.json()["detail"]["message"]
    assert "/var/private/juris-token" not in response.text
    assert "token=abc123" not in response.text
    assert "pin=1234" not in response.text


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


def test_workbench_endpoint_returns_daily_queues(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")

    monkeypatch.setattr(app_module, "_tenant_db", lambda tenant: "db")
    monkeypatch.setattr(app_module, "_out_root", lambda: tmp_path)
    monkeypatch.setattr(app_module, "list_processos", lambda db=None: [])
    monkeypatch.setattr(app_module, "list_prazos", lambda db=None: [])
    monkeypatch.setattr(
        app_module,
        "build_workbench",
        lambda *, processos, prazos, out_root: {
            "critical_deadlines": [],
            "recent_movements": [],
            "draft_ready": [],
            "blocked_cases": [{"numero_cnj": "A"}],
            "recent_artifacts": [],
        },
    )

    response = client.get("/api/workbench")

    assert response.status_code == 200
    assert response.json()["blocked_cases"][0]["numero_cnj"] == "A"


def test_pilot_feedback_endpoints_are_tenant_scoped(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")

    monkeypatch.setattr(app_module, "_out_root", lambda: tmp_path)
    payload = {
        "numero_cnj": "0001234-56.2026.8.13.0001",
        "output_dir": "juris-out/CASE",
        "time_saved_minutes": 30,
        "mode_used": "minuta",
        "citations_accepted": 2,
        "citations_rejected": 1,
        "missing_source": "TJMG acórdão",
        "deadline_or_analysis_error": "",
        "perceived_utility": 4,
        "corpus_usable": True,
        "notes": "validar corpus",
    }

    created = client.post("/api/pilot-feedback", json=payload)
    listed = client.get("/api/pilot-feedback")
    summary = client.get("/api/pilot-feedback/summary")
    comparison = client.get("/api/pilot-feedback/comparison")
    exported = client.get("/api/pilot-feedback/export", params={"format": "csv"})
    report = client.get("/api/pilot-feedback/export", params={"format": "md"})

    assert created.status_code == 201, created.text
    assert created.json()["feedback"]["time_saved_minutes"] == 30
    assert listed.status_code == 200
    assert listed.json()["feedback"][0]["numero_cnj"] == "0001234-56.2026.8.13.0001"
    assert summary.status_code == 200
    assert summary.json()["total_time_saved_minutes"] == 30
    assert summary.json()["prioritized_gaps"][0]["label"] == "TJMG acórdão"
    assert comparison.status_code == 200
    assert comparison.json()["compared_cases"] == 0
    assert exported.status_code == 200
    assert "TJMG acórdão" in exported.text
    assert report.status_code == 200
    assert "# Relatório do Piloto Juris" in report.text


def test_corpus_queue_endpoints(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.pilot_feedback import append_feedback

    monkeypatch.setattr(app_module, "_out_root", lambda: tmp_path)
    monkeypatch.setenv("JURIS_REPERTORY_PATH", str(tmp_path / "repertory.db"))
    append_feedback(
        tmp_path,
        {
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "output_dir": "juris-out/CASE",
            "time_saved_minutes": 15,
            "mode_used": "rascunho",
            "citations_accepted": 1,
            "citations_rejected": 0,
            "missing_source": "acórdão STJ",
            "deadline_or_analysis_error": "",
            "perceived_utility": 4,
            "corpus_usable": True,
            "notes": "",
        },
    )
    payload = {
        "numero_cnj": "0001234-56.2026.8.13.0001",
        "title": "REsp aprovado",
        "source_url": "https://example.test/resp",
        "source_date": "2026-06-30",
        "source_type": "acordao_publicado",
        "tribunal": "STJ",
        "area": "civel",
        "tema": "cobranca",
        "status": "vigente",
        "source_text": "inteiro teor",
    }

    candidates = client.get("/api/corpus/candidates")
    created = client.post("/api/corpus/sources", json=payload)
    sources = client.get("/api/corpus/sources")
    coverage = client.get("/api/corpus/coverage")

    assert candidates.status_code == 200
    assert candidates.json()["candidates"][0]["missing_source"] == "acórdão STJ"
    assert created.status_code == 201, created.text
    source_id = created.json()["source"]["id"]
    assert created.json()["source"]["content_sha256"]
    assert sources.json()["sources"][0]["tribunal"] == "STJ"
    assert coverage.json()["coverage"]["source_type"]["acordao_publicado"] == 1

    marked = client.post(f"/api/corpus/sources/{source_id}/reingested")
    assert marked.status_code == 200
    assert marked.json()["source"]["reingest_status"] == "done"


def test_corpus_source_rejects_excessive_source_text(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")

    monkeypatch.setattr(app_module, "_out_root", lambda: tmp_path)
    payload = {
        "numero_cnj": "0001234-56.2026.8.13.0001",
        "title": "REsp aprovado",
        "source_url": "https://example.test/resp",
        "source_date": "2026-06-30",
        "source_type": "acordao_publicado",
        "tribunal": "STJ",
        "area": "civel",
        "tema": "cobranca",
        "status": "vigente",
        "source_text": "x" * (app_module._MAX_CORPUS_SOURCE_TEXT + 1),
    }

    response = client.post("/api/corpus/sources", json=payload)

    assert response.status_code == 422


def test_corpus_reingest_endpoint_writes_repertory(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")

    monkeypatch.setattr(app_module, "_out_root", lambda: tmp_path)
    monkeypatch.setenv("JURIS_REPERTORY_PATH", str(tmp_path / "repertory.db"))
    created = client.post(
        "/api/corpus/sources",
        json={
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "title": "Acórdão aprovado",
            "source_url": "https://example.test/resp",
            "source_date": "2026-06-30",
            "source_type": "acordao_publicado",
            "tribunal": "STJ",
            "area": "civel",
            "tema": "cobranca",
            "status": "vigente",
            "source_text": "EMENTA. Cobrança. VOTO. Recurso provido.",
        },
    )
    assert created.status_code == 201, created.text

    response = client.post("/api/corpus/reingest")

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    assert response.json()["chunks"] >= 1


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
    assert body["output_dir"].startswith("DEMO-")
    assert str(tmp_path) not in body["output_dir"]
    assert body["artifacts"][0]["name"] == "rascunho-pesquisa.md"
    assert body["artifacts"][0]["path"] == "rascunho-pesquisa.md"
    assert body["artifacts"][0]["preview"].startswith("# Rascunho real")


def test_endpoints_enforce_api_key_when_tenants_configured(tmp_path, monkeypatch) -> None:
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


def test_invalid_tenant_error_is_structured(tmp_path, monkeypatch) -> None:
    from juris.web import auth

    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": "secret-key"}), encoding="utf-8")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    auth.default_registry.cache_clear()
    try:
        response = client.get("/api/prazos", headers={"X-API-Key": "wrong"})
    finally:
        auth.default_registry.cache_clear()

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "tenant_invalid"


def test_validate_startup_config_fails_closed_without_tenants(monkeypatch) -> None:
    from juris.web import auth

    app_module = importlib.import_module("juris.web.app")
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.delenv("JURIS_TENANTS_FILE", raising=False)
    auth.default_registry.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="JURIS_TENANTS_FILE"):
            app_module.validate_startup_config()
    finally:
        auth.default_registry.cache_clear()


def test_validate_startup_config_requires_agent_binding_per_tenant(tmp_path, monkeypatch) -> None:
    from juris.api.agent_config import _load_agent_bindings
    from juris.web import auth

    app_module = importlib.import_module("juris.web.app")
    tenants = tmp_path / "tenants.json"
    agents = tmp_path / "agents.json"
    tenants.write_text(json.dumps({"escritorio-a": "key-a", "escritorio-b": "key-b"}), encoding="utf-8")
    agents.write_text(json.dumps({"escritorio-a": {"url": "ws://a.local:8765", "token": "tok-a"}}), encoding="utf-8")
    monkeypatch.setenv("JURIS_REQUIRE_TENANTS", "1")
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    auth.default_registry.cache_clear()
    _load_agent_bindings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="escritorio-b"):
            app_module.validate_startup_config()
    finally:
        auth.default_registry.cache_clear()
        _load_agent_bindings.cache_clear()


def test_api_rate_limit_is_per_api_key(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.rate_limit import FixedWindowRateLimiter

    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60)
    monkeypatch.setattr(app_module, "_api_rate_limiter", lambda: limiter)

    first = client.get("/api/agent-mode", headers={"X-API-Key": "a"})
    blocked = client.get("/api/agent-mode", headers={"X-API-Key": "a"})
    other_key = client.get("/api/agent-mode", headers={"X-API-Key": "b"})

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "rate_limited"
    assert other_key.status_code == 200


def test_api_rate_limit_groups_invalid_keys_by_client(tmp_path, monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web import auth
    from juris.web.rate_limit import FixedWindowRateLimiter

    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": "valid-key"}), encoding="utf-8")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    auth.default_registry.cache_clear()
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60)
    monkeypatch.setattr(app_module, "_api_rate_limiter", lambda: limiter)

    try:
        first = client.get("/api/prazos", headers={"X-API-Key": "wrong-a"})
        blocked = client.get("/api/prazos", headers={"X-API-Key": "wrong-b"})
    finally:
        auth.default_registry.cache_clear()

    assert first.status_code == 401
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "rate_limited"


def test_connect_job_hidden_from_non_owner(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.connect_jobs import ConnectJobStore

    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("job-y", "escritorio-a")  # owned by escritorio-a
    monkeypatch.setattr(app_module, "_connect_job_store", lambda: store)
    # invisible to the public caller (open default)
    assert client.get("/api/connect/job-y").status_code == 404


def test_connect_job_hidden_from_other_configured_tenant(tmp_path, monkeypatch) -> None:
    from juris.web import auth
    from juris.web.connect_jobs import ConnectJobStore

    app_module = importlib.import_module("juris.web.app")
    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": "key-a", "escritorio-b": "key-b"}), encoding="utf-8")
    store = ConnectJobStore(tmp_path / "jobs.db")
    store.create("job-a", "escritorio-a")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setattr(app_module, "_connect_job_store", lambda: store)
    auth.default_registry.cache_clear()
    try:
        assert client.get("/api/connect/job-a", headers={"X-API-Key": "key-b"}).status_code == 404
        assert client.get("/api/connect/job-a", headers={"X-API-Key": "key-a"}).status_code == 200
    finally:
        auth.default_registry.cache_clear()


def test_demo_run_output_root_is_tenant_scoped(tmp_path, monkeypatch) -> None:
    from juris.web import auth

    app_module = importlib.import_module("juris.web.app")
    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": "key-a", "escritorio-b": "key-b"}), encoding="utf-8")
    captured: list[Path] = []

    async def fake_execute(request):
        captured.append(request.out_root)
        return WebDemoRun(
            succeeded=True,
            degraded=False,
            degradation_reason="",
            errors=(),
            duration_seconds=0.1,
            output_dir=str(request.out_root / "CASE"),
            artifacts=(),
        )

    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setattr(app_module, "execute_demo_run", fake_execute)
    auth.default_registry.cache_clear()
    payload = {
        "numero_cnj": "0001234-56.2026.8.13.0001",
        "tipo": "contestacao",
        "source": "fixture",
    }
    try:
        assert client.post("/api/demo-runs", json=payload, headers={"X-API-Key": "key-a"}).status_code == 200
        assert client.post("/api/demo-runs", json=payload, headers={"X-API-Key": "key-b"}).status_code == 200
    finally:
        auth.default_registry.cache_clear()

    assert captured == [
        tmp_path / "out" / "tenants" / "escritorio-a",
        tmp_path / "out" / "tenants" / "escritorio-b",
    ]


def test_audit_endpoint_cannot_escape_to_other_tenant_root(tmp_path, monkeypatch) -> None:
    from juris.web import auth

    tenants = tmp_path / "tenants.json"
    tenants.write_text(json.dumps({"escritorio-a": "key-a", "escritorio-b": "key-b"}), encoding="utf-8")
    monkeypatch.setenv("JURIS_TENANTS_FILE", str(tenants))
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path / "out"))
    auth.default_registry.cache_clear()
    try:
        response = client.get(
            "/api/audit",
            params={"output_dir": "../escritorio-a/CASE"},
            headers={"X-API-Key": "key-b"},
        )
    finally:
        auth.default_registry.cache_clear()

    assert response.status_code == 400


def test_localdb_is_cached_per_path(tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    path = str(tmp_path / "tenant.db")
    # same path → same LocalDB instance (engine/pool reused, not rebuilt per request)
    assert app_module._localdb_for_path(path) is app_module._localdb_for_path(path)


def test_ai_session_endpoint_returns_mode() -> None:
    body = client.get("/api/ai-session").json()
    assert body["mode"] in {"browser_session", "cloud_deid", "local"}
    assert "deidentify" in body
    assert body["browser"]["status"] in {"ready", "agent_offline", "needs_native_host", "disabled"}
    assert "message" in body["browser"]


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


def test_connect_remote_mode_accepts_no_cpf(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.jobs.connect import ConnectResult

    async def fake_run_connect(*a, **k):
        return ConnectResult(avisos_added=0, seed_added=0, total_tracked=0, first_time=True, sync=None)

    monkeypatch.setattr(app_module, "run_connect", fake_run_connect)
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    # remote: neither cpf nor pin/senha needed — the agent resolves them
    response = client.post("/api/connect", json={"tribunal": "tjmg", "sync": False})
    assert response.status_code == 202, response.text


def test_demo_run_remote_agent_failure_is_controlled_not_500(monkeypatch, tmp_path) -> None:
    from juris.web import demo_service

    def _boom(*a, **k):
        raise RuntimeError("tenant 'x' sem binding de agente próprio (fail-closed)")

    monkeypatch.setattr(demo_service, "_build_llm", lambda *, use_cloud: object())
    monkeypatch.setattr(demo_service, "_build_repertory", lambda _p: object())
    monkeypatch.setattr(demo_service, "load_processo", _boom)

    response = client.post(
        "/api/demo-runs",
        json={
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "tipo": "contestacao",
            "source": "mni",
            "out_root": str(tmp_path),
        },
    )

    assert response.status_code == 400, response.status_code  # controlled, not a 500
    assert response.json()["detail"]["code"] == "agent_mni_failed"
    assert "agente/MNI" in response.json()["detail"]["message"]
    assert "binding" not in response.text
    assert "fail-closed" not in response.text


def test_agent_mode_endpoint_reports_remote(monkeypatch) -> None:
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    response = client.get("/api/agent-mode")
    assert response.status_code == 200
    assert response.json()["remote"] is True


def test_agent_mode_endpoint_reports_inprocess(monkeypatch) -> None:
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    response = client.get("/api/agent-mode")
    assert response.status_code == 200
    assert response.json()["remote"] is False


def test_agent_health_inprocess_does_not_require_agent(monkeypatch) -> None:
    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)

    response = client.get("/api/agent-health")

    assert response.status_code == 200
    body = response.json()
    assert body["remote"] is False
    assert body["agent_required"] is False
    assert body["error"] is None


def test_agent_health_remote_reports_tenant_agent(monkeypatch) -> None:
    from juris.api import pairing
    from juris.api.ws_schemas import HealthResponse

    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    monkeypatch.setattr(
        pairing,
        "check_agent_health",
        lambda url: HealthResponse(
            status="ok",
            token_connected=True,
            cert_valid_until=date(2030, 1, 2),
            version="1.2.3",
        ),
    )

    response = client.get("/api/agent-health")

    assert response.status_code == 200
    body = response.json()
    assert body["remote"] is True
    assert body["agent_configured"] is True
    assert body["reachable"] is True
    assert body["token_connected"] is True
    assert body["cert_valid_until"] == "2030-01-02"
    assert body["ready"] is True
    assert body["status"] == "ready"
    assert body["error_code"] is None


def test_agent_health_remote_reports_token_absent(monkeypatch) -> None:
    from juris.api import pairing
    from juris.api.ws_schemas import HealthResponse

    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    monkeypatch.setattr(
        pairing,
        "check_agent_health",
        lambda url: HealthResponse(
            status="ok",
            token_connected=False,
            cert_valid_until=None,
            version="1.2.3",
        ),
    )

    response = client.get("/api/agent-health")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["ready"] is False
    assert body["status"] == "token_absent"
    assert body["error_code"] == "agent_token_missing"
    assert "token A3" in body["message"]


def test_agent_health_remote_reports_expired_certificate(monkeypatch) -> None:
    from juris.api import pairing
    from juris.api.ws_schemas import HealthResponse

    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    monkeypatch.setattr(
        pairing,
        "check_agent_health",
        lambda url: HealthResponse(
            status="ok",
            token_connected=True,
            cert_valid_until=date(2020, 1, 2),
            version="1.2.3",
        ),
    )

    response = client.get("/api/agent-health")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["token_connected"] is True
    assert body["ready"] is False
    assert body["status"] == "cert_expired"
    assert body["error_code"] == "agent_cert_expired"
    assert "vencido" in body["message"]


def test_agent_health_remote_unmapped_tenant_reports_error(tmp_path, monkeypatch) -> None:
    from juris.api.agent_config import _load_agent_bindings

    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"escritorio-a": {"url": "ws://a.local:8765", "token": "tok-a"}}), encoding="utf-8")
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    _load_agent_bindings.cache_clear()
    try:
        response = client.get("/api/agent-health")
    finally:
        _load_agent_bindings.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["remote"] is True
    assert body["reachable"] is False
    assert body["ready"] is False
    assert body["status"] == "missing_binding"
    assert body["error_code"] == "agent_missing"
    assert "sem binding" in body["error"]


def test_agent_health_remote_does_not_leak_internal_error(monkeypatch) -> None:
    from juris.api import pairing

    def _raise(_url):
        raise RuntimeError("connection refused token=abc pin=1234 /var/private/cert")

    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    monkeypatch.setattr(pairing, "check_agent_health", _raise)

    response = client.get("/api/agent-health")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["ready"] is False
    assert body["status"] == "offline"
    assert body["error_code"] == "agent_offline"
    assert "Agente remoto configurado" in body["error"]
    assert "token=abc" not in response.text
    assert "pin=1234" not in response.text
    assert "/var/private/cert" not in response.text


def test_filing_status_is_scoped_to_the_tenant(monkeypatch, tmp_path) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.auth import Tenant

    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.setattr("juris.web.filing_console.filing_status", lambda root=None: {"root": str(root)})

    app_module.app.dependency_overrides[app_module.current_tenant] = lambda: Tenant("escritorio-a")
    try:
        root_a = client.get("/api/filing/status").json()["root"]
        app_module.app.dependency_overrides[app_module.current_tenant] = lambda: Tenant("escritorio-b")
        root_b = client.get("/api/filing/status").json()["root"]
    finally:
        app_module.app.dependency_overrides.clear()

    # each firm's filing status reads ONLY its own scoped dir — no shared global root
    assert root_a == str(tmp_path / "tenants" / "escritorio-a" / "filings")
    assert root_b == str(tmp_path / "tenants" / "escritorio-b" / "filings")
    assert root_a != root_b


def test_uncaught_exception_returns_sanitized_500(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")
    from juris.web.auth import Tenant

    def _boom(*a, **k):
        raise RuntimeError("internal secret: token=abc123")

    monkeypatch.setattr(app_module, "_tenant_db", lambda tenant: object())
    monkeypatch.setattr(app_module, "list_processos", _boom)
    app_module.app.dependency_overrides[app_module.current_tenant] = lambda: Tenant("t")
    # a non-raising client so we observe the handler's 500 response, not a re-raise
    quiet_client = TestClient(app, raise_server_exceptions=False)
    try:
        response = quiet_client.get("/api/processos")
    finally:
        app_module.app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    assert "token=abc123" not in response.text  # never leak the internal detail/traceback


def test_agent_relay_rejects_bad_token(monkeypatch) -> None:
    from fastapi import WebSocketDisconnect

    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://x:1")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "right-token")
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/agent-relay?tenant=public", headers={"x-agent-token": "wrong"}),
    ):
        pass


def test_agent_relay_rejects_token_in_query_string(monkeypatch) -> None:
    from fastapi import WebSocketDisconnect

    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://x:1")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "right-token")
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/agent-relay?tenant=public&token=right-token"),
    ):
        pass


def test_agent_relay_registers_then_unregisters(monkeypatch) -> None:
    import time

    from juris.api.relay import get_relay_hub

    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://x:1")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    hub = get_relay_hub()
    hub.unregister("public")

    with client.websocket_connect("/ws/agent-relay?tenant=public", headers={"x-agent-token": "tok"}):
        deadline = time.time() + 2
        while not hub.is_connected("public") and time.time() < deadline:
            time.sleep(0.02)
        assert hub.is_connected("public") is True  # agent dialed in and registered

    deadline = time.time() + 2
    while hub.is_connected("public") and time.time() < deadline:
        time.sleep(0.02)
    assert hub.is_connected("public") is False  # unregistered on disconnect


def test_health_ok_when_dependencies_reachable() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["connect_jobs"] == "ok"


def test_health_degraded_when_database_down(monkeypatch) -> None:
    app_module = importlib.import_module("juris.web.app")

    def _boom(_path):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(app_module, "_localdb_for_path", _boom)
    resp = client.get("/health")
    assert resp.status_code == 503  # readiness fails so an LB can route away
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "error"
