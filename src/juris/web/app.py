"""FastAPI app for the local Juris pilot UI."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from juris import __version__
from juris.core.paths import juris_home
from juris.jobs.connect import run_connect
from juris.web.auth import Tenant, current_tenant, tenant_db_path
from juris.web.connect_jobs import ConnectJobStore
from juris.web.demo_service import DemoRunError, WebDemoRunRequest, execute_demo_run
from juris.web.processos_service import get_processo_detail, list_prazos, list_processos
from juris.web.rate_limit import FixedWindowRateLimiter
from juris.web.workbench_service import build_workbench

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


def _juris_home() -> Path:
    """The ``~/.juris`` base for filing receipts + audit chain (JURIS_HOME overridable)."""
    return juris_home()


def _tenant_juris_home(tenant: Tenant) -> Path:
    """The tenant's ``~/.juris`` — isolates filing receipts + audit per firm."""
    from juris.web.auth import tenant_scoped_dir

    return tenant_scoped_dir(tenant, _juris_home())


def _tenant_filing_root(tenant: Tenant) -> Path:
    """The tenant's filing-receipts root (``<tenant home>/filings``)."""
    return _tenant_juris_home(tenant) / "filings"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_startup_config()
    # Recover jobs orphaned by a crash/restart: any 'running' row older than the
    # per-job timeout can never complete, so mark it errored on boot.
    with suppress(Exception):  # never block startup on housekeeping
        _connect_job_store().sweep_stale(_CONNECT_JOB_TIMEOUT_SECONDS)
    yield


app = FastAPI(
    title="Juris Web",
    version=__version__,
    description="Local browser UI for the Juris pilot demo workflow.",
    lifespan=_lifespan,
)

_STATIC_DIR = Path(__file__).with_name("static")
_INDEX_PATH = _STATIC_DIR / "index.html"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


@lru_cache(maxsize=1)
def _api_rate_limiter() -> FixedWindowRateLimiter:
    limit = int(os.environ.get("JURIS_API_RATE_LIMIT_PER_MINUTE", "120"))
    return FixedWindowRateLimiter(limit=limit, window_seconds=60)


@app.middleware("http")
async def _rate_limit_api(request: Request, call_next: Any) -> Any:
    """Basic per-API-key burst protection for web API routes."""
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    key = _api_rate_limit_key(request)
    decision = _api_rate_limiter().check(key)
    if decision.allowed:
        return await call_next(request)
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(decision.retry_after_seconds)},
        content={
            "detail": {
                "code": "rate_limited",
                "message": "Limite de requisições excedido para esta API key.",
                "retry_after_seconds": decision.retry_after_seconds,
            }
        },
    )


def _api_rate_limit_key(request: Request) -> str:
    """Rate-limit valid API keys individually; group invalid keys by client IP."""
    from juris.web.auth import default_registry, hash_api_key

    raw_key = request.headers.get("X-API-Key")
    registry = default_registry()
    if registry.is_open:
        return hash_api_key(raw_key) if raw_key else "public"
    tenant = registry.authenticate(raw_key)
    if tenant is not None:
        return f"tenant:{tenant.tenant_id}:{hash_api_key(raw_key or '')}"
    client_host = request.client.host if request.client else "unknown"
    return f"invalid:{client_host}"


@app.exception_handler(Exception)
async def _handle_uncaught(request: Request, exc: Exception) -> JSONResponse:
    """Turn any uncaught exception into a sanitized 500.

    The traceback/internal message is logged (structlog), never serialized to the
    client — a stack trace on the wire leaks paths, config, and secrets.
    """
    from juris.core.observability import get_logger
    from juris.core.sanitize import safe_error_text

    get_logger("juris.web").error(
        "unhandled_exception",
        path=request.url.path,
        error=safe_error_text(exc),
        exception_type=exc.__class__.__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal_error", "message": "Erro interno no servidor."}},
    )


def _operational_http_error(
    *, code: str, message: str, exc: Exception, internal_detail: str | None = None
) -> HTTPException:
    """Build a sanitized 400 while logging the internal operational detail."""
    from juris.core.observability import get_logger
    from juris.core.sanitize import safe_error_text

    get_logger("juris.web").warning(
        "operational_http_error",
        code=code,
        error=safe_error_text(internal_detail or exc),
        exception_type=exc.__class__.__name__,
    )
    return HTTPException(
        status_code=400,
        detail={"code": code, "message": message},
    )


def validate_startup_config() -> None:
    """Fail closed for production multi-tenant deployments.

    ``JURIS_REQUIRE_TENANTS=1`` means the web process must not silently fall back
    to the shared public tenant, and remote agent mode must have one binding per
    configured tenant.
    """
    from juris.api.agent_config import is_remote, tenant_agent_binding
    from juris.web.auth import default_registry

    if not _env_flag("JURIS_REQUIRE_TENANTS"):
        return

    registry = default_registry()
    if registry.is_open:
        msg = "JURIS_REQUIRE_TENANTS=1 exige JURIS_TENANTS_FILE com pelo menos um tenant."
        raise RuntimeError(msg)

    if is_remote():
        for tenant_id in registry.tenant_ids:
            tenant_agent_binding(tenant_id)


_MAX_SHORT_TEXT = 10_000
_MAX_PATH_TEXT = 512
_MAX_URL_TEXT = 2_048
_MAX_DRAFT_MARKDOWN = 1_000_000
_MAX_CORPUS_SOURCE_TEXT = 2_000_000


class DemoRunPayload(BaseModel):
    """JSON payload submitted by the local web UI."""

    numero_cnj: str = Field(min_length=1, max_length=64)
    tipo: str = Field(default="contestacao", max_length=64)
    tribunal: str = Field(default="tjmg", max_length=32)
    source: str = Field(default="fixture", max_length=32)
    modo: str = Field(default="rascunho-pesquisa", max_length=64)
    out_root: str = Field(default="juris-out", max_length=_MAX_PATH_TEXT)
    thesis: str | None = Field(default=None, max_length=_MAX_SHORT_TEXT)
    instructions: str = Field(default="", max_length=_MAX_SHORT_TEXT)
    cloud: bool = False
    skip_review: bool = False
    use_cache: bool = True
    cpf: str | None = Field(default=None, max_length=32)  # co-located; remote agent resolves it


class PilotFeedbackPayload(BaseModel):
    """Structured feedback from one real pilot case."""

    numero_cnj: str = Field(min_length=1, max_length=64)
    output_dir: str | None = Field(default=None, max_length=_MAX_PATH_TEXT)
    time_saved_minutes: int = Field(ge=0)
    mode_used: str = Field(pattern="^(minuta|rascunho)$")
    citations_accepted: int = Field(default=0, ge=0)
    citations_rejected: int = Field(default=0, ge=0)
    missing_source: str = Field(default="", max_length=_MAX_SHORT_TEXT)
    deadline_or_analysis_error: str = Field(default="", max_length=_MAX_SHORT_TEXT)
    perceived_utility: int = Field(ge=1, le=5)
    corpus_usable: bool = False
    notes: str = Field(default="", max_length=_MAX_SHORT_TEXT)


class CorpusSourcePayload(BaseModel):
    """Lawyer-approved source to enter the pilot-directed corpus queue."""

    numero_cnj: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    source_url: str = Field(min_length=1, max_length=_MAX_URL_TEXT)
    source_date: str = Field(min_length=1, max_length=32)
    source_type: str = Field(min_length=1, max_length=64)
    tribunal: str = Field(min_length=1, max_length=32)
    area: str = Field(min_length=1, max_length=128)
    tema: str = Field(min_length=1, max_length=256)
    status: str = Field(default="vigente", max_length=64)
    content_sha256: str | None = Field(default=None, max_length=64)
    source_text: str | None = Field(default=None, max_length=_MAX_CORPUS_SOURCE_TEXT)
    notes: str = Field(default="", max_length=_MAX_SHORT_TEXT)


class FilingPayload(BaseModel):
    """Controlled filing request from the web console."""

    numero_cnj: str = Field(min_length=1, max_length=64)
    tribunal: str = Field(default="tjmg", max_length=32)
    tipo_documento: str = Field(default="manifestacao", max_length=64)
    tipo_peticao: str = Field(default="manifestacao", max_length=64)
    draft_markdown: str = Field(min_length=1, max_length=_MAX_DRAFT_MARKDOWN)
    cpf: str | None = Field(default=None, max_length=32)
    senha: str | None = Field(default=None, max_length=256)
    pin: str | None = Field(default=None, max_length=128)
    prazo_override: str | None = Field(default=None, max_length=64)
    review_confirmed: bool = False
    consent: bool = False


class FilingArtifactPayload(BaseModel):
    """Draft artifact selected for controlled filing."""

    output_dir: str = Field(min_length=1, max_length=_MAX_PATH_TEXT)
    artifact_name: str = Field(min_length=1, max_length=128)


class PendingRecoveryPayload(BaseModel):
    """One pending filing selected for recovery."""

    pending_key: str = Field(min_length=1, max_length=_MAX_PATH_TEXT)


class PendingArchivePayload(PendingRecoveryPayload):
    """Explicit manual resolution of a pending filing."""

    reason: str = Field(min_length=1, max_length=_MAX_SHORT_TEXT)
    confirm_manual_resolution: bool = False


def _readiness() -> dict[str, object]:
    """Probe the real dependencies (DB + jobs store), not just liveness."""
    from juris.web.auth import PUBLIC_TENANT_ID

    def _probe_db() -> None:
        _localdb_for_path(str(tenant_db_path(Tenant(PUBLIC_TENANT_ID)))).ping()

    def _probe_jobs() -> None:
        _connect_job_store().get("__health__")

    checks: dict[str, str] = {}
    healthy = True
    for name, probe in (("database", _probe_db), ("connect_jobs", _probe_jobs)):
        try:
            probe()
            checks[name] = "ok"
        except Exception:  # noqa: BLE001 — any failure ⇒ this dependency is down
            checks[name] = "error"
            healthy = False
    return {"status": "ok" if healthy else "degraded", "checks": checks}


@app.get("/health")
async def health() -> Response:
    """Readiness probe: liveness + real DB/jobs-store connectivity (503 when degraded)."""
    result = _readiness()
    code = 200 if result["status"] == "ok" else 503
    return JSONResponse(status_code=code, content={"version": __version__, **result})


@app.get("/api/health")
async def get_tenant_health(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Per-tenant operational health — config, storage, corpus, agent, browser bridge.

    Scoped to the authenticated tenant; never touches another firm's data.
    """
    from juris.ops.tenant_health import tenant_operational_status

    return tenant_operational_status(tenant)


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
_CONNECT_JOB_TIMEOUT_SECONDS = int(os.environ.get("JURIS_CONNECT_TIMEOUT_SECONDS", "900"))
_CONNECT_JOB_ERROR = (
    "Falha operacional ao conectar/sincronizar. Verifique agente, token e credenciais locais."
)
# Strong refs to in-flight background tasks so the event loop doesn't GC them mid-run.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


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
        result = await asyncio.wait_for(
            run_connect(
                tribunal_cfg,
                payload.cpf or "",  # remote: the agent resolves the lawyer's own CPF
                payload.senha or payload.cpf or "",
                token_pin=payload.pin,
                seed_text=payload.seed_text,
                do_sync=payload.sync,
                db=_tenant_db(tenant),
                tenant_id=tenant.tenant_id,
            ),
            timeout=_CONNECT_JOB_TIMEOUT_SECONDS,  # a hung MNI/agent call can't leave the job "running"
        )
        store.mark_done(job_id, _serialize_connect(result))
    except TimeoutError:
        store.mark_error(job_id, "tempo excedido ao conectar/sincronizar (timeout)")
    except Exception as exc:  # noqa: BLE001 — surfaced to the client via the job
        from juris.core.observability import get_logger
        from juris.core.sanitize import safe_error_text

        get_logger("juris.web").warning(
            "connect_job_error",
            job_id=job_id,
            tenant_id=tenant.tenant_id,
            error=safe_error_text(exc),
            exception_type=exc.__class__.__name__,
        )
        store.mark_error(job_id, _CONNECT_JOB_ERROR)


@app.post("/api/connect", status_code=202)
async def create_connect(
    payload: ConnectPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Start an async import/update; returns a job id to poll (connect can take minutes)."""
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
    store.evict_old(_MAX_CONNECT_JOBS, tenant_id=tenant.tenant_id)
    # Retain a reference so the task isn't garbage-collected mid-run (asyncio caveat)
    # and use create_task (not the deprecated get_event_loop().create_task).
    task = asyncio.create_task(_run_connect_job(job_id, tribunal_cfg, payload, tenant))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return {"job_id": job_id, "status": "running"}


@app.websocket("/ws/agent-relay")
async def agent_relay_socket(ws: WebSocket) -> None:
    """Reverse channel (ADR-0015 Phase 2): the lawyer's agent dials IN (outbound) and
    holds this connection open; the orchestrator routes token ops down it, sidestepping
    the agent's NAT. The agent authenticates with its tenant's shared token."""
    from juris.api.relay import get_relay_hub, relay_token_ok
    from juris.api.ws_schemas import AgentResponse
    from juris.web.auth import validate_tenant_id

    try:
        tenant_id = validate_tenant_id(ws.query_params.get("tenant", "public"))
    except ValueError:
        await ws.close(code=4001, reason="Unauthorized")
        return
    # The relay is cloud-facing: never accept the shared secret in the URL, which
    # can be captured by access logs, browser history, or intermediary telemetry.
    token = ws.headers.get("x-agent-token")
    if not relay_token_ok(tenant_id, token):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()
    hub = get_relay_hub()

    async def _send(payload: str) -> None:
        await ws.send_text(payload)

    connection_id = hub.register(tenant_id, _send)
    try:
        while True:  # agent → cloud replies, correlated by request_id
            hub.resolve(tenant_id, AgentResponse.model_validate_json(await ws.receive_text()))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(tenant_id, connection_id)


@app.get("/api/agent-mode")
async def get_agent_mode() -> dict[str, object]:
    """Tell the UI whether token ops are remote (the local agent resolves secrets) or
    co-located. In remote the connect/new-case forms must hide CPF/PIN and send only
    {tribunal, sync}; co-located source=mni still needs the CPF (ADR-0015)."""
    from juris.api.agent_config import agent_mode, is_remote

    return {"remote": is_remote(), "mode": agent_mode()}


@app.get("/api/agent-health")
async def get_agent_health(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Tenant-scoped readiness of the split-trust local agent.

    In in-process mode there is no remote agent to probe. In remote mode, resolve
    this tenant's binding and call its /health endpoint. The shared token is never
    returned.
    """
    from juris.api.agent_config import agent_mode, is_remote, tenant_agent_binding
    from juris.api.pairing import check_agent_health
    from juris.web.auth import default_registry

    remote = is_remote()
    payload: dict[str, object] = {
        "tenant_id": tenant.tenant_id,
        "tenant_configured": not default_registry().is_open,
        "mode": agent_mode(),
        "remote": remote,
        "agent_required": remote,
        "agent_configured": not remote,
        "binding_present": None if not remote else False,
        "reachable": None,
        "token_connected": None,
        "cert_valid_until": None,
        "version": None,
        "ready": not remote,
        "status": "inprocess" if not remote else "checking",
        "message": "Operando em modo co-localizado." if not remote else None,
        "error_code": None,
        "error": None,
    }
    if not remote:
        return payload

    try:
        binding = tenant_agent_binding(tenant.tenant_id)
        payload["agent_configured"] = True
        payload["binding_present"] = True
        health = check_agent_health(binding.base_url)
    except Exception as exc:  # noqa: BLE001 — health reports readiness, not stack traces
        code = _agent_health_error_code(str(exc))
        from juris.core.observability import get_logger
        from juris.core.sanitize import safe_error_text

        message = _agent_health_message(code)
        get_logger("juris.web").warning(
            "agent_health_error",
            tenant_id=tenant.tenant_id,
            code=code,
            error=safe_error_text(exc),
            exception_type=exc.__class__.__name__,
        )
        payload["reachable"] = False
        payload["ready"] = False
        payload["status"] = _agent_health_status(code)
        payload["message"] = message
        payload["error_code"] = code
        payload["error"] = message
        return payload

    cert_valid_until = health.cert_valid_until
    cert_expired = cert_valid_until is not None and cert_valid_until < date.today()
    ready = bool(health.token_connected and not cert_expired)
    if ready:
        status = "ready"
        error_code = None
        message = "Agente remoto pronto: token A3 conectado."
    elif cert_expired:
        status = "cert_expired"
        error_code = "agent_cert_expired"
        message = "Agente remoto alcançável, mas o certificado do token está vencido."
    else:
        status = "token_absent"
        error_code = "agent_token_missing"
        message = "Agente remoto alcançável, mas o token A3 não foi detectado."

    payload.update(
        {
            "reachable": True,
            "token_connected": health.token_connected,
            "cert_valid_until": cert_valid_until.isoformat() if cert_valid_until else None,
            "version": health.version,
            "ready": ready,
            "status": status,
            "message": message,
            "error_code": error_code,
        }
    )
    return payload


def _agent_health_error_code(message: str) -> str:
    lower = message.lower()
    if "sem binding" in lower or "incompleto" in lower:
        return "agent_missing"
    if (
        "inacessível" in lower
        or "inacessivel" in lower
        or "connection" in lower
        or "refused" in lower
        or "timeout" in lower
    ):
        return "agent_offline"
    if "token ausente" in lower or "sem token" in lower or "token a3" in lower:
        return "agent_token_missing"
    return "agent_unavailable"


def _agent_health_status(error_code: str) -> str:
    return {
        "agent_missing": "missing_binding",
        "agent_token_missing": "token_absent",
        "agent_cert_expired": "cert_expired",
        "agent_offline": "offline",
    }.get(error_code, "unavailable")


def _agent_health_message(error_code: str) -> str:
    return {
        "agent_missing": "Tenant sem binding de agente remoto.",
        "agent_token_missing": "Agente remoto sem token A3 conectado.",
        "agent_cert_expired": "Agente remoto com certificado do token vencido.",
        "agent_offline": "Agente remoto configurado, mas inacessível.",
    }.get(error_code, "Agente remoto indisponível.")


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


@app.get("/api/workbench")
async def get_workbench(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Daily workbench queues for the lawyer console."""
    from juris.web.auth import tenant_scoped_dir

    db = _tenant_db(tenant)
    return build_workbench(
        processos=list_processos(db=db),
        prazos=list_prazos(db=db),
        out_root=tenant_scoped_dir(tenant, _out_root()),
        filing_root=_tenant_filing_root(tenant),
    )


@app.post("/api/pilot-feedback", status_code=201)
async def create_pilot_feedback(
    payload: PilotFeedbackPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Record structured value/quality feedback for one pilot case."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import append_feedback

    root = tenant_scoped_dir(tenant, _out_root())
    record = append_feedback(root, payload.model_dump())
    return {"feedback": record}


@app.get("/api/pilot-feedback")
async def get_pilot_feedback(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """List pilot feedback records for this tenant."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import list_feedback

    return {"feedback": list_feedback(tenant_scoped_dir(tenant, _out_root()))}


@app.get("/api/pilot-feedback/summary")
async def get_pilot_feedback_summary(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Aggregate pilot feedback into metrics, gaps, and corpus candidates."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import summarize_feedback

    return summarize_feedback(tenant_scoped_dir(tenant, _out_root()))


@app.get("/api/pilot-feedback/comparison")
async def get_pilot_feedback_comparison(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Compare first vs latest feedback for cases run more than once."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import compare_feedback_runs

    return compare_feedback_runs(tenant_scoped_dir(tenant, _out_root()))


@app.get("/api/corpus/candidates")
async def get_corpus_candidates(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Pilot feedback records that should be evaluated for corpus expansion."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import corpus_candidates

    return {"candidates": corpus_candidates(tenant_scoped_dir(tenant, _out_root()))}


@app.post("/api/corpus/sources", status_code=201)
async def create_corpus_source(
    payload: CorpusSourcePayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Record an accepted source with mandatory provenance."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import append_accepted_source

    try:
        source = append_accepted_source(tenant_scoped_dir(tenant, _out_root()), payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source": source}


@app.get("/api/corpus/sources")
async def get_corpus_sources(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Accepted pilot-directed corpus sources for this tenant."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import list_accepted_sources

    return {"sources": list_accepted_sources(tenant_scoped_dir(tenant, _out_root()))}


@app.get("/api/corpus/coverage")
async def get_corpus_coverage(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Coverage and reingestion queue for the pilot-directed corpus."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import coverage_report

    return coverage_report(tenant_scoped_dir(tenant, _out_root()))


@app.post("/api/corpus/sources/{source_id}/reingested")
async def mark_corpus_source_reingested(
    source_id: str, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Mark a queued source as reingested after the controlled corpus job runs."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import mark_reingested

    source = mark_reingested(tenant_scoped_dir(tenant, _out_root()), source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="fonte não encontrada")
    return {"source": source}


@app.post("/api/corpus/reingest")
async def reingest_pilot_corpus(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Run controlled reingestion for pending pilot-directed corpus sources."""
    from juris.repertory.readiness import resolve_repertory_path
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import reingest_pending_sources

    report = reingest_pending_sources(
        tenant_scoped_dir(tenant, _out_root()), resolve_repertory_path(), tenant_id=tenant.tenant_id
    )
    return report.to_dict()


@app.get("/api/pilot-feedback/export")
async def export_pilot_feedback(
    export_format: str = Query("json", alias="format"),
    tenant: Tenant = Depends(current_tenant),
) -> Response:
    """Export pilot feedback as JSON or CSV for commercial/product review."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import export_feedback_csv, export_feedback_json, export_feedback_report_markdown

    root = tenant_scoped_dir(tenant, _out_root())
    if export_format == "csv":
        return Response(export_feedback_csv(root), media_type="text/csv")
    if export_format == "json":
        return Response(export_feedback_json(root), media_type="application/json")
    if export_format == "md":
        return Response(export_feedback_report_markdown(root), media_type="text/markdown")
    raise HTTPException(status_code=400, detail="format deve ser json, csv ou md")


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


@app.get("/api/filing/status")
async def get_filing_status(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Pending filings and recent custody chains — scoped to THIS tenant's filings."""
    from juris.web.filing_console import filing_status

    return filing_status(_tenant_filing_root(tenant))


@app.get("/api/filing/artifacts")
async def get_filing_artifacts(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Recent draft artifacts that can prefill the controlled filing form."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.filing_console import filing_artifacts

    return filing_artifacts(tenant_scoped_dir(tenant, _out_root()))


@app.post("/api/filing/artifacts/content")
async def get_filing_artifact_content(
    payload: FilingArtifactPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Read a selected primary draft artifact, confined to this tenant's output root."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.filing_console import read_filing_artifact

    try:
        return read_filing_artifact(
            tenant_scoped_dir(tenant, _out_root()),
            output_dir=payload.output_dir,
            artifact_name=payload.artifact_name,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/filing/pending/recovery")
async def recover_pending_filing(
    payload: PendingRecoveryPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Recovery checklist for one pending filing, without exposing signed PDF bytes."""
    from juris.web.filing_console import pending_recovery

    try:
        return pending_recovery(_tenant_filing_root(tenant), payload.pending_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/filing/pending/archive")
async def archive_pending_filing(
    payload: PendingArchivePayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Archive a pending filing only after explicit manual resolution."""
    from juris.web.filing_console import archive_pending

    if not payload.confirm_manual_resolution:
        raise HTTPException(status_code=400, detail="confirmação manual é obrigatória para arquivar")
    try:
        return archive_pending(_tenant_filing_root(tenant), payload.pending_key, reason=payload.reason)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/filing/dry-run")
async def dry_run_filing(
    payload: FilingPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Render and preflight a filing without signing or contacting the tribunal."""
    from juris.signing.filing import FilingRequest
    from juris.signing.filing_service import get_filing_service
    from juris.web.filing_console import serialize_filing_result

    remote = _is_remote_agent_mode()
    _require_filing_credentials(payload, remote=remote)
    request = FilingRequest(
        numero_cnj=payload.numero_cnj.strip(),
        tribunal=payload.tribunal.strip() or "tjmg",
        tipo_documento=payload.tipo_documento.strip() or "manifestacao",
        draft_markdown=payload.draft_markdown,
        tipo_peticao=payload.tipo_peticao.strip() or "manifestacao",
        cpf="" if remote else payload.cpf or "",
        senha="" if remote else payload.senha or "",
        dry_run=True,
        prazo_override=payload.prazo_override,
    )
    try:
        result = await get_filing_service(
            tenant.tenant_id, storage_root=_tenant_juris_home(tenant)
        ).file(
            request,
            pin=None if remote else payload.pin,
        )
    except Exception as exc:  # noqa: BLE001 — operational filing error, not 500
        raise _operational_http_error(
            code="filing_failed",
            message="Falha operacional no protocolo. Verifique agente, token e tribunal.",
            exc=exc,
        ) from exc
    return serialize_filing_result(result)


@app.post("/api/filing/submit")
async def submit_filing(
    payload: FilingPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Sign and file only after review confirmation and explicit lawyer consent."""
    from juris.signing.filing import FilingRequest
    from juris.signing.filing_service import get_filing_service
    from juris.web.filing_console import serialize_filing_result

    if not payload.review_confirmed:
        raise HTTPException(status_code=400, detail="Confirme a revisão humana antes de protocolar.")
    if not payload.consent:
        raise HTTPException(status_code=400, detail="Consentimento explícito é obrigatório antes de assinar.")

    remote = _is_remote_agent_mode()
    _require_filing_credentials(payload, remote=remote)
    request = FilingRequest(
        numero_cnj=payload.numero_cnj.strip(),
        tribunal=payload.tribunal.strip() or "tjmg",
        tipo_documento=payload.tipo_documento.strip() or "manifestacao",
        draft_markdown=payload.draft_markdown,
        tipo_peticao=payload.tipo_peticao.strip() or "manifestacao",
        cpf="" if remote else payload.cpf or "",
        senha="" if remote else payload.senha or "",
        dry_run=False,
        prazo_override=payload.prazo_override,
    )
    try:
        result = await get_filing_service(
            tenant.tenant_id, storage_root=_tenant_juris_home(tenant)
        ).file(
            request,
            pin=None if remote else payload.pin,
        )
    except Exception as exc:  # noqa: BLE001 — operational filing error, not 500
        raise _operational_http_error(
            code="filing_failed",
            message="Falha operacional no protocolo. Verifique agente, token e tribunal.",
            exc=exc,
        ) from exc
    return serialize_filing_result(result)


def _is_remote_agent_mode() -> bool:
    from juris.api.agent_config import is_remote

    return is_remote()


def _require_filing_credentials(payload: FilingPayload, *, remote: bool) -> None:
    if remote:
        return
    missing = [
        name
        for name, value in (("CPF", payload.cpf), ("senha", payload.senha), ("PIN", payload.pin))
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"{', '.join(missing)} obrigatório(s) no modo co-localizado.",
        )


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
        raise _operational_http_error(
            code=exc.code,
            message=str(exc),
            exc=exc,
            internal_detail=exc.internal_detail,
        ) from exc

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
