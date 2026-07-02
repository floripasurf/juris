"""FastAPI app for the local Juris pilot UI."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from juris import __version__
from juris.config import get_settings
from juris.core.paths import juris_home
from juris.jobs.connect import run_connect
from juris.web.auth import Tenant, current_tenant, require_admin, tenant_db_path
from juris.web.connect_jobs import ConnectJobStore
from juris.web.demo_service import DemoRunError, WebDemoRunRequest, execute_demo_run
from juris.web.processos_service import get_processo_detail, list_prazos, list_processos
from juris.web.rate_limit import RateLimiter, build_rate_limiter
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


@lru_cache(maxsize=1)
def _corpus_search_service(repertory_path: Path) -> Any:
    """Cached repertory service for /api/corpus/search — the heavy embedder/reranker
    load once, not per request. Tenant scoping happens per-query (shared store)."""
    from juris.web.demo_service import _build_repertory

    return _build_repertory(repertory_path)


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
        _connect_job_store().sweep_stale(_connect_job_timeout_seconds())
    yield


app = FastAPI(
    title="Juris Web",
    version=__version__,
    description="Local browser UI for the Juris pilot demo workflow.",
    lifespan=_lifespan,
)

_STATIC_DIR = Path(__file__).with_name("static")
_INDEX_PATH = _STATIC_DIR / "index.html"
_ASSETS_DIR = _STATIC_DIR / "assets"
_PUBLIC_HTTPS_HOSTS = frozenset(
    {
        "causia.com.br",
        "www.causia.com.br",
        "app.causia.com.br",
        "juris.blackcube.dev",
    }
)
_EXPENSIVE_API_PREFIXES = (
    "/api/demo-runs",
    "/api/corpus/search",
    "/api/corpus/reingest",
    "/api/corpus/upload",
    "/api/filing/dry-run",
    "/api/filing/submit",
)


@lru_cache(maxsize=1)
def _api_rate_limiter() -> RateLimiter:
    # Shared Redis quota when JURIS_RATE_LIMIT_REDIS_URL is set (multi-worker SaaS);
    # process-local otherwise (single-worker pilot).
    settings = get_settings()
    return build_rate_limiter(
        limit=settings.api_rate_limit_per_minute,
        window_seconds=60,
        redis_url=settings.rate_limit_redis_url or None,
        prefix="juris:rl:api:",
    )


@lru_cache(maxsize=1)
def _api_expensive_rate_limiter() -> RateLimiter:
    settings = get_settings()
    return build_rate_limiter(
        limit=settings.api_expensive_rate_limit_per_minute,
        window_seconds=60,
        redis_url=settings.rate_limit_redis_url or None,
        prefix="juris:rl:api-expensive:",
    )


@lru_cache(maxsize=1)
def _ws_agent_relay_rate_limiter() -> RateLimiter:
    settings = get_settings()
    return build_rate_limiter(
        limit=settings.ws_agent_relay_rate_limit_per_minute,
        window_seconds=60,
        redis_url=settings.rate_limit_redis_url or None,
        prefix="juris:rl:ws-agent-relay:",
    )


def _api_rate_limiter_for_path(path: str) -> RateLimiter:
    if path.startswith(_EXPENSIVE_API_PREFIXES):
        return _api_expensive_rate_limiter()
    return _api_rate_limiter()


def _request_host(request: Request) -> str:
    return request.headers.get("host", "").split(":", 1)[0].lower()


def _forwarded_proto(request: Request) -> str:
    return request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip().lower()


def _is_public_https_host(request: Request) -> bool:
    return _request_host(request) in _PUBLIC_HTTPS_HOSTS


def _add_hsts_if_public_https(request: Request, response: Response) -> Response:
    if _is_public_https_host(request) and _forwarded_proto(request) == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


@app.middleware("http")
async def _rate_limit_api(request: Request, call_next: Any) -> Any:
    """Basic per-API-key burst protection for web API routes."""
    if _is_public_https_host(request) and _forwarded_proto(request) == "http":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    if not request.url.path.startswith("/api/"):
        return _add_hsts_if_public_https(request, await call_next(request))
    key = _api_rate_limit_key(request)
    decision = _api_rate_limiter_for_path(request.url.path).check(key)
    if decision.allowed:
        return _add_hsts_if_public_https(request, await call_next(request))
    response = JSONResponse(
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
    return _add_hsts_if_public_https(request, response)


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


def _ws_agent_relay_rate_limit_key(ws: WebSocket, tenant_id: str) -> str:
    client_host = ws.client.host if ws.client else "unknown"
    return f"tenant:{tenant_id}:host:{client_host}"


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

    ``JURIS_REQUIRE_TENANTS=1`` or ``ENVIRONMENT=prod`` means the web process must
    not silently fall back to the shared public tenant, and remote agent mode must
    have one binding per configured tenant.
    """
    from juris.api.agent_config import is_remote, tenant_agent_binding
    from juris.web.auth import default_registry, require_tenants_enabled

    if not require_tenants_enabled():
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


class CorpusUploadPayload(BaseModel):
    """Office-archive document uploaded from the console into the corpus."""

    source_text: str = Field(default="", max_length=_MAX_CORPUS_SOURCE_TEXT)
    filename: str = Field(default="", max_length=255)
    content_base64: str = Field(default="", max_length=28_000_000)  # ~20MB decodificados
    title: str = Field(default="", max_length=512)
    source_type: str = Field(default="acordao_publicado", max_length=64)
    source_date: str = Field(default="", max_length=32)
    source_url: str = Field(default="", max_length=_MAX_URL_TEXT)
    tribunal: str = Field(default="", max_length=32)
    source_publisher: str = Field(default="", max_length=128)
    tema: str = Field(default="", max_length=256)
    area: str = Field(default="", max_length=128)
    numero_cnj: str = Field(default="", max_length=64)


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


class PendingRetryPayload(PendingRecoveryPayload):
    """Controlled retry of an already signed pending filing."""

    cpf: str | None = Field(default=None, max_length=32)
    senha: str | None = Field(default=None, max_length=256)
    tribunal: str | None = Field(default=None, max_length=32)
    tipo_documento: str | None = Field(default=None, max_length=64)
    confirm_no_existing_protocol: bool = False


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
    result = await asyncio.to_thread(_readiness)
    code = 200 if result["status"] == "ok" else 503
    return JSONResponse(status_code=code, content={"version": __version__, **result})


@app.get("/api/health")
async def get_tenant_health(deep: bool = True, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Per-tenant operational health — config, storage, corpus, agent, browser bridge.

    Scoped to the authenticated tenant; never touches another firm's data. ``deep``
    (default) actually PROBES the remote agent over the network, so a required-but-
    unreachable agent shows red instead of a falsely-green "binding configured". Pass
    ``?deep=false`` for a fast shallow check (binding presence only).
    """
    from juris.ops.tenant_health import tenant_operational_status

    return await asyncio.to_thread(tenant_operational_status, tenant, deep=deep)


@app.get("/api/admin/health")
async def get_admin_health(deep: bool = True, _: None = Depends(require_admin)) -> dict[str, object]:
    """Cross-tenant operational panel — every firm's health at once (admin-gated).

    Requires ``$JURIS_ADMIN_TOKEN`` via the ``x-admin-token`` header; disabled (404)
    when unset. Lets the operator see, per tenant, which firm is degraded (agent/token/
    bridge down) before the firm calls.
    """
    from juris.ops.tenant_health import tenant_operational_status
    from juris.web.auth import Tenant, default_registry

    reg = default_registry()
    tenant_ids = list(reg.tenant_ids) if not reg.is_open else ["public"]
    tenants = await asyncio.gather(
        *(asyncio.to_thread(tenant_operational_status, Tenant(tid), deep=deep) for tid in sorted(tenant_ids))
    )
    return {
        "tenants": tenants,
        "degraded": [t["tenant_id"] for t in tenants if t["status"] != "ok"],
    }


@app.get("/api/ai-session")
async def get_ai_session() -> dict[str, object]:
    """Active AI mode + de-id posture, for the operator console badge (ADR-0016/0018)."""
    from juris.web.ai_status import resolve_ai_session_status

    return resolve_ai_session_status()


@app.get("/api/processos")
async def get_processos(
    limit: int = 50, offset: int = 0, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """List the lawyer's imported processos (paginated) with their nearest pending prazo.

    Backend pagination: ``limit`` (clamped 1–200) + ``offset``, plus ``total`` so the UI
    can page a large acervo without loading it all.
    """
    from juris.web.processos_service import list_processos_page

    page, total = await asyncio.to_thread(list_processos_page, db=_tenant_db(tenant), limit=limit, offset=offset)
    return {
        "processos": [v.to_dict() for v in page],
        "total": total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
    }


@app.get("/api/processos/{numero_cnj}")
async def get_processo(numero_cnj: str, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Detail for one processo: metadata + movements + pending prazos."""
    detail = await asyncio.to_thread(get_processo_detail, numero_cnj, db=_tenant_db(tenant))
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
_CONNECT_JOB_ERROR = "Falha operacional ao conectar/sincronizar. Verifique agente, token e credenciais locais."
# Strong refs to in-flight background tasks so the event loop doesn't GC them mid-run.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


@lru_cache(maxsize=1)
def _connect_job_store() -> ConnectJobStore:
    return ConnectJobStore()


def _connect_job_timeout_seconds() -> int:
    return get_settings().connect_timeout_seconds


async def _run_connect_job(job_id: str, tribunal_cfg: TribunalConfig, payload: ConnectPayload, tenant: Tenant) -> None:
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
            timeout=_connect_job_timeout_seconds(),  # a hung MNI/agent call can't leave the job "running"
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
async def create_connect(payload: ConnectPayload, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
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
        raise HTTPException(status_code=400, detail="CPF e PIN do token são obrigatórios no modo co-localizado.")

    job_id = uuid.uuid4().hex

    def _create_job() -> None:
        store = _connect_job_store()
        store.create(job_id, tenant.tenant_id)
        store.evict_old(_MAX_CONNECT_JOBS, tenant_id=tenant.tenant_id)

    await asyncio.to_thread(_create_job)
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
    decision = _ws_agent_relay_rate_limiter().check(_ws_agent_relay_rate_limit_key(ws, tenant_id))
    if not decision.allowed:
        await ws.close(code=4008, reason="Rate limited")
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
            await hub.resolve_async(tenant_id, AgentResponse.model_validate_json(await ws.receive_text()))
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
        health = await asyncio.to_thread(check_agent_health, binding.base_url)
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
async def get_connect(job_id: str, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Poll a connect job — only the tenant that started it can read it (durable store)."""
    job = await asyncio.to_thread(_connect_job_store().get, job_id)
    if job is None or job.get("tenant_id") != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@app.get("/api/prazos")
async def get_prazos(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Deadline agenda: pending prazos across the acervo, soonest first."""
    prazos = await asyncio.to_thread(list_prazos, db=_tenant_db(tenant))
    return {"prazos": [v.to_dict() for v in prazos]}


@app.get("/api/workbench")
async def get_workbench(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Daily workbench queues for the lawyer console."""
    from juris.web.auth import tenant_scoped_dir

    db = _tenant_db(tenant)

    def _build() -> dict[str, object]:
        return build_workbench(
            processos=list_processos(db=db),
            prazos=list_prazos(db=db),
            out_root=tenant_scoped_dir(tenant, _out_root()),
            filing_root=_tenant_filing_root(tenant),
            sync_status=db.get_sync_overview(),
        )

    return await asyncio.to_thread(_build)


@app.post("/api/pilot-feedback", status_code=201)
async def create_pilot_feedback(
    payload: PilotFeedbackPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Record structured value/quality feedback for one pilot case."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import append_feedback

    root = tenant_scoped_dir(tenant, _out_root())
    record = await asyncio.to_thread(append_feedback, root, payload.model_dump())
    return {"feedback": record}


@app.get("/api/pilot-feedback")
async def get_pilot_feedback(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """List pilot feedback records for this tenant."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import list_feedback

    feedback = await asyncio.to_thread(list_feedback, tenant_scoped_dir(tenant, _out_root()))
    return {"feedback": feedback}


@app.get("/api/pilot-feedback/summary")
async def get_pilot_feedback_summary(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Aggregate pilot feedback into metrics, gaps, and corpus candidates."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import summarize_feedback

    return await asyncio.to_thread(summarize_feedback, tenant_scoped_dir(tenant, _out_root()))


@app.get("/api/pilot-feedback/comparison")
async def get_pilot_feedback_comparison(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Compare first vs latest feedback for cases run more than once."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.pilot_feedback import compare_feedback_runs

    return await asyncio.to_thread(compare_feedback_runs, tenant_scoped_dir(tenant, _out_root()))


@app.get("/api/corpus/candidates")
async def get_corpus_candidates(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Pilot feedback records that should be evaluated for corpus expansion."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import corpus_candidates

    candidates = await asyncio.to_thread(corpus_candidates, tenant_scoped_dir(tenant, _out_root()))
    return {"candidates": candidates}


@app.post("/api/corpus/sources", status_code=201)
async def create_corpus_source(
    payload: CorpusSourcePayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Record an accepted source with mandatory provenance."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import append_accepted_source

    try:
        source = await asyncio.to_thread(
            append_accepted_source,
            tenant_scoped_dir(tenant, _out_root()),
            payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source": source}


@app.get("/api/corpus/sources")
async def get_corpus_sources(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Accepted pilot-directed corpus sources for this tenant."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import list_accepted_sources

    sources = await asyncio.to_thread(list_accepted_sources, tenant_scoped_dir(tenant, _out_root()))
    return {"sources": sources}


@app.get("/api/corpus/coverage")
async def get_corpus_coverage(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Coverage and reingestion queue for the pilot-directed corpus."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import coverage_report

    return await asyncio.to_thread(coverage_report, tenant_scoped_dir(tenant, _out_root()))



def _repertory_has_chunks(path: Path) -> bool:
    """Uploads do escritório contam como corpus pesquisável mesmo sem as seeds públicas."""
    import sqlite3

    if not path.is_file():
        return False
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone()
    except sqlite3.Error:
        return False
    return row is not None


@app.get("/api/corpus/search")
async def search_corpus(q: str, top_k: int = 8, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Explainable jurisprudence search (Sprint 5): each hit carries WHY it ranked.

    Tenant-scoped (public seed + this firm's own uploads only). Every result exposes
    the ranking signals — fonte, autoridade, vigência, corroboração and the strongest
    ``motivo`` — so the console shows not just *what* was retrieved but *why* it was
    trusted (``explain_ranking``, ADR-0017).
    """
    from juris.repertory.readiness import read_status, resolve_repertory_path
    from juris.repertory.retrieval.service import explain_ranking

    status = await asyncio.to_thread(read_status)
    if not status.is_ready and not await asyncio.to_thread(
        _repertory_has_chunks, resolve_repertory_path()
    ):
        return {"query": q, "results": [], "detail": "corpus não ingerido ainda"}

    def _search() -> list[Any]:
        repertory = _corpus_search_service(resolve_repertory_path())
        raw_results = repertory.search_jurisprudencia(query=q, top_k=max(1, min(top_k, 20)), tenant_id=tenant.tenant_id)
        return cast(list[Any], raw_results)

    results = await asyncio.to_thread(_search)
    return {
        "query": q,
        "results": [
            {
                "source_id": r.source_id,
                "score": r.score,
                "tribunal": r.tribunal,
                "hierarquia": r.hierarchy_label,
                "texto": r.texto[:400],
                "explain": explain_ranking(r),
            }
            for r in results
        ],
    }


@app.post("/api/corpus/sources/{source_id}/reingested")
async def mark_corpus_source_reingested(source_id: str, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Mark a queued source as reingested after the controlled corpus job runs."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import mark_reingested

    source = await asyncio.to_thread(mark_reingested, tenant_scoped_dir(tenant, _out_root()), source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="fonte não encontrada")
    return {"source": source}



@app.post("/api/corpus/upload", status_code=201)
async def upload_corpus_document(
    payload: CorpusUploadPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Acervo do escritório → corpus: registra com proveniência e ingere na hora.

    Único caminho de inteiro teor aprovado no ToS log (documentos que o
    escritório já possui). O texto entra tagueado pelo tenant (tier privado).
    """
    from juris.repertory.readiness import resolve_repertory_path
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import upload_source_document

    try:
        return await asyncio.to_thread(
            upload_source_document,
            tenant_scoped_dir(tenant, _out_root()),
            resolve_repertory_path(),
            payload.model_dump(),
            tenant.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "corpus_upload_invalid", "message": str(exc)},
        ) from exc


@app.post("/api/corpus/reingest")
async def reingest_pilot_corpus(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Run controlled reingestion for pending pilot-directed corpus sources."""
    from juris.repertory.readiness import resolve_repertory_path
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import reingest_pending_sources

    report = await asyncio.to_thread(
        reingest_pending_sources,
        tenant_scoped_dir(tenant, _out_root()),
        resolve_repertory_path(),
        tenant_id=tenant.tenant_id,
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
        return Response(await asyncio.to_thread(export_feedback_csv, root), media_type="text/csv")
    if export_format == "json":
        return Response(await asyncio.to_thread(export_feedback_json, root), media_type="application/json")
    if export_format == "md":
        return Response(await asyncio.to_thread(export_feedback_report_markdown, root), media_type="text/markdown")
    raise HTTPException(status_code=400, detail="format deve ser json, csv ou md")


@app.get("/api/audit")
async def get_audit(output_dir: str, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
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
        return await asyncio.to_thread(audit_view, audit_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="audit.jsonl não encontrado") from exc


@app.get("/api/filing/status")
async def get_filing_status(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Pending filings and recent custody chains — scoped to THIS tenant's filings."""
    from juris.web.filing_console import filing_status

    return await asyncio.to_thread(filing_status, _tenant_filing_root(tenant))


@app.get("/api/filing/artifacts")
async def get_filing_artifacts(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Recent draft artifacts that can prefill the controlled filing form."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.filing_console import filing_artifacts

    return await asyncio.to_thread(filing_artifacts, tenant_scoped_dir(tenant, _out_root()))


@app.post("/api/filing/artifacts/content")
async def get_filing_artifact_content(
    payload: FilingArtifactPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Read a selected primary draft artifact, confined to this tenant's output root."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.filing_console import read_filing_artifact

    try:
        return await asyncio.to_thread(
            read_filing_artifact,
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
        return await asyncio.to_thread(pending_recovery, _tenant_filing_root(tenant), payload.pending_key)
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
        return await asyncio.to_thread(
            archive_pending,
            _tenant_filing_root(tenant),
            payload.pending_key,
            reason=payload.reason,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/filing/pending/retry")
async def retry_pending_filing(
    payload: PendingRetryPayload, tenant: Tenant = Depends(current_tenant)
) -> dict[str, object]:
    """Retry the submit step for a signed pending filing after human reconciliation."""
    from juris.web.filing_console import retry_pending_submission

    if _is_remote_agent_mode():
        raise HTTPException(
            status_code=400,
            detail=(
                "retry de _pending remoto deve ser executado no agente local; "
                "a nuvem não acessa signed.pdf nem credenciais"
            ),
        )
    if not (payload.cpf and payload.senha):
        raise HTTPException(status_code=400, detail="CPF e senha são obrigatórios para retry co-localizado")
    try:
        return await asyncio.to_thread(
            retry_pending_submission,
            _tenant_filing_root(tenant),
            payload.pending_key,
            cpf=payload.cpf,
            senha=payload.senha,
            confirm_no_existing_protocol=payload.confirm_no_existing_protocol,
            tribunal=payload.tribunal,
            tipo_documento=payload.tipo_documento,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/filing/dry-run")
async def dry_run_filing(payload: FilingPayload, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
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
        result = await get_filing_service(tenant.tenant_id, storage_root=_tenant_juris_home(tenant)).file(
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
async def submit_filing(payload: FilingPayload, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
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
        result = await get_filing_service(tenant.tenant_id, storage_root=_tenant_juris_home(tenant)).file(
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
        name for name, value in (("CPF", payload.cpf), ("senha", payload.senha), ("PIN", payload.pin)) if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"{', '.join(missing)} obrigatório(s) no modo co-localizado.",
        )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Render the local operator UI."""
    return await asyncio.to_thread(_INDEX_PATH.read_text, encoding="utf-8")


@app.api_route("/static/assets/{asset_path:path}", methods=["GET", "HEAD"])
async def static_asset(asset_path: str) -> FileResponse:
    """Serve checked-in UI assets without exposing arbitrary local files."""
    asset = (_ASSETS_DIR / asset_path).resolve()
    try:
        asset.relative_to(_ASSETS_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Asset not found.") from exc
    if not asset.is_file():
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(asset)


@app.post("/api/demo-runs")
async def create_demo_run(payload: DemoRunPayload, tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
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
