"""FastAPI app for the local Juris pilot UI."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from juris import __version__
from juris.jobs.connect import run_connect
from juris.web.auth import Tenant, current_tenant, tenant_db_path
from juris.web.connect_jobs import ConnectJobStore
from juris.web.demo_service import DemoRunError, WebDemoRunRequest, execute_demo_run
from juris.web.processos_service import get_processo_detail, list_prazos, list_processos

if TYPE_CHECKING:
    from juris.mni.tribunais import TribunalConfig
    from juris.persistence.local_db import LocalDB


@lru_cache(maxsize=128)
def _localdb_for_path(path: str) -> LocalDB:
    """One cached LocalDB per storage path — reuse its engine/pool across requests."""
    from juris.persistence.local_db import LocalDB

    return LocalDB(Path(path))


def _tenant_db(tenant: Tenant) -> LocalDB:
    """A LocalDB scoped to the tenant's storage (isolated per firm; shared for public)."""
    return _localdb_for_path(str(tenant_db_path(tenant)))


def _out_root() -> Path:
    """Server-controlled output root — clients can't choose where runs are written."""
    return Path(os.environ.get("JURIS_OUT_ROOT", "juris-out"))

app = FastAPI(
    title="Juris Web",
    version=__version__,
    description="Local browser UI for the Juris pilot demo workflow.",
)

_STATIC_DIR = Path(__file__).with_name("static")
_INDEX_PATH = _STATIC_DIR / "index.html"


class DemoRunPayload(BaseModel):
    """JSON payload submitted by the local web UI."""

    numero_cnj: str = Field(min_length=1)
    tipo: str = "contestacao"
    tribunal: str = "tjmg"
    source: str = "fixture"
    modo: str = "rascunho-pesquisa"
    out_root: str = "juris-out"
    thesis: str | None = None
    instructions: str = ""
    cloud: bool = False
    skip_review: bool = False
    use_cache: bool = True
    cpf: str | None = None  # co-located source=mni; in remote the agent resolves it


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for the local web UI."""
    return {"status": "ok", "version": __version__}


@app.get("/api/ai-session")
async def get_ai_session() -> dict[str, object]:
    """Active AI mode + de-id posture, for the operator console badge (ADR-0016/0018)."""
    from juris.web.ai_status import resolve_ai_session_status

    return resolve_ai_session_status()


@app.get("/api/processos")
async def get_processos(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """List the lawyer's imported processos with their nearest pending prazo."""
    return {"processos": [v.to_dict() for v in list_processos(db=_tenant_db(tenant))]}


@app.get("/api/processos/{numero_cnj}")
async def get_processo(
    numero_cnj: str, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Detail for one processo: metadata + movements + pending prazos."""
    detail = get_processo_detail(numero_cnj, db=_tenant_db(tenant))
    if detail is None:
        raise HTTPException(status_code=404, detail="processo não encontrado")
    return detail.to_dict()


class ConnectPayload(BaseModel):
    """Connect request.

    Co-located (Phase 1): the token PIN + PJe senha are entered locally and sent.
    Remote (split-trust): they are **omitted** — the lawyer's agent resolves them;
    the cloud orchestrator never receives the secret (ADR-0015).
    """

    cpf: str | None = None  # required only co-located; remote agent resolves it
    tribunal: str = "tjmg"
    pin: str | None = None  # required only in co-located mode (see create_connect)
    senha: str | None = None
    seed_text: str | None = None
    sync: bool = True


def _serialize_connect(result: Any) -> dict[str, object]:
    return {
        "avisos_added": result.avisos_added,
        "seed_added": result.seed_added,
        "total_tracked": result.total_tracked,
        "first_time": result.first_time,
        "seed_errors": result.seed_errors,
        "sync": None
        if result.sync is None
        else {
            "total": result.sync.total,
            "succeeded": result.sync.succeeded,
            "failed": result.sync.failed,
            "critical_alerts": result.sync.total_critical_alerts,
        },
    }


# Durable connect jobs — a SQLite-backed store survives restart/deploy and scopes
# each job to its owning tenant (Phase 2). The PIN is never persisted (it lives only
# in the transient background-task closure, then is GC'd).
_MAX_CONNECT_JOBS = 200


@lru_cache(maxsize=1)
def _connect_job_store() -> ConnectJobStore:
    return ConnectJobStore()


async def _run_connect_job(
    job_id: str, tribunal_cfg: TribunalConfig, payload: ConnectPayload, tenant: Tenant
) -> None:
    """Background worker: run the (possibly slow) connect and record the outcome.

    Writes go to the tenant's own store (isolation); the job carries its
    ``tenant_id`` so only the owning tenant can read it back.
    """
    from juris.core.observability import bind_tenant_log_context

    bind_tenant_log_context(tenant.tenant_id)  # background task runs in its own context
    store = _connect_job_store()
    try:
        result = await run_connect(
            tribunal_cfg,
            payload.cpf or "",  # remote: the agent resolves the lawyer's own CPF
            payload.senha or payload.cpf or "",
            token_pin=payload.pin,
            seed_text=payload.seed_text,
            do_sync=payload.sync,
            db=_tenant_db(tenant),
            tenant_id=tenant.tenant_id,
        )
        store.mark_done(job_id, _serialize_connect(result))
    except Exception as exc:  # noqa: BLE001 — surfaced to the client via the job
        store.mark_error(job_id, str(exc))


@app.post("/api/connect", status_code=202)
async def create_connect(
    payload: ConnectPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Start an async import/update; returns a job id to poll (connect can take minutes)."""
    import asyncio
    import uuid

    from juris.mni.tribunais import get_tribunal

    try:
        tribunal_cfg = get_tribunal(payload.tribunal)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Tribunal desconhecido: {payload.tribunal}") from exc
    if not tribunal_cfg.requires_mtls:
        raise HTTPException(status_code=400, detail="connect suporta apenas tribunais mTLS (ex.: tjmg).")

    # Split-trust: the PIN/senha are required only co-located. In remote mode the
    # agent resolves them — the cloud must not carry the lawyer's secret.
    from juris.api.agent_config import is_remote

    if not is_remote() and not (payload.pin and payload.cpf):
        raise HTTPException(
            status_code=400, detail="CPF e PIN do token são obrigatórios no modo co-localizado."
        )

    job_id = uuid.uuid4().hex
    store = _connect_job_store()
    store.create(job_id, tenant.tenant_id)
    store.evict_old(_MAX_CONNECT_JOBS)
    asyncio.get_event_loop().create_task(_run_connect_job(job_id, tribunal_cfg, payload, tenant))
    return {"job_id": job_id, "status": "running"}


@app.get("/api/connect/{job_id}")
async def get_connect(
    job_id: str, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Poll a connect job — only the tenant that started it can read it (durable store)."""
    job = _connect_job_store().get(job_id)
    if job is None or job.get("tenant_id") != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@app.get("/api/prazos")
async def get_prazos(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Deadline agenda: pending prazos across the acervo, soonest first."""
    return {"prazos": [v.to_dict() for v in list_prazos(db=_tenant_db(tenant))]}


@app.get("/api/audit")
async def get_audit(
    output_dir: str, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """The audit chain + integrity verdict for a demo run's output dir.

    The path is resolved and confined to the tenant's output root, so the endpoint
    can't read arbitrary local files or another tenant's audit log.
    """
    from juris.web.audit_service import audit_view, resolve_audit_path
    from juris.web.auth import tenant_scoped_dir

    root = tenant_scoped_dir(tenant, _out_root())
    try:
        audit_path = resolve_audit_path(output_dir, root=root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return audit_view(audit_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="audit.jsonl não encontrado") from exc


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Render the local operator UI."""
    return _INDEX_PATH.read_text(encoding="utf-8")


@app.post("/api/demo-runs")
async def create_demo_run(
    payload: DemoRunPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Run the demo pipeline from a browser request."""
    from juris.web.auth import tenant_scoped_dir

    # payload.out_root is ignored — the server controls where runs are written.
    request = WebDemoRunRequest(
        numero_cnj=payload.numero_cnj.strip(),
        tipo=payload.tipo,
        tribunal=payload.tribunal.strip() or "tjmg",
        source=payload.source,
        modo=payload.modo,
        out_root=tenant_scoped_dir(tenant, _out_root()),
        thesis=payload.thesis.strip() if payload.thesis else None,
        instructions=payload.instructions,
        cloud=payload.cloud,
        skip_review=payload.skip_review,
        use_cache=payload.use_cache,
        tenant_id=tenant.tenant_id,  # source=mni routes to this firm's agent
        cpf=payload.cpf,
    )
    try:
        result = await execute_demo_run(request)
    except DemoRunError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "succeeded": result.succeeded,
        "degraded": result.degraded,
        "degradation_reason": result.degradation_reason,
        "errors": list(result.errors),
        "duration_seconds": result.duration_seconds,
        "output_dir": result.output_dir,
        "artifacts": [
            {
                "name": artifact.name,
                "path": artifact.path,
                "sha256": artifact.sha256,
                "preview": artifact.preview,
            }
            for artifact in result.artifacts
        ],
        "estrategia": result.estrategia,
        "review": result.review,
        "grounding": result.grounding,  # anti-hallucination chip (first-class state)
    }
