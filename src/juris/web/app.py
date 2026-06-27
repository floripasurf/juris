"""FastAPI app for the local Juris pilot UI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from juris import __version__
from juris.jobs.connect import run_connect
from juris.web.demo_service import DemoRunError, WebDemoRunRequest, execute_demo_run
from juris.web.processos_service import get_processo_detail, list_prazos, list_processos

if TYPE_CHECKING:
    from juris.mni.tribunais import TribunalConfig

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


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for the local web UI."""
    return {"status": "ok", "version": __version__}


@app.get("/api/processos")
async def get_processos() -> dict[str, object]:
    """List the lawyer's imported processos with their nearest pending prazo."""
    return {"processos": [v.to_dict() for v in list_processos()]}


@app.get("/api/processos/{numero_cnj}")
async def get_processo(numero_cnj: str) -> dict[str, object]:
    """Detail for one processo: metadata + movements + pending prazos."""
    detail = get_processo_detail(numero_cnj)
    if detail is None:
        raise HTTPException(status_code=404, detail="processo não encontrado")
    return detail.to_dict()


class ConnectPayload(BaseModel):
    """Connect request — co-located Phase 1: the token PIN is entered locally."""

    cpf: str = Field(min_length=1)
    tribunal: str = "tjmg"
    pin: str = Field(min_length=1)
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


# In-memory connect jobs (co-located Phase 1, single process). Phase 2: a real queue.
_CONNECT_JOBS: dict[str, dict[str, object]] = {}


async def _run_connect_job(job_id: str, tribunal_cfg: TribunalConfig, payload: ConnectPayload) -> None:
    """Background worker: run the (possibly slow) connect and record the outcome."""
    try:
        result = await run_connect(
            tribunal_cfg,
            payload.cpf,
            payload.senha or payload.cpf,
            token_pin=payload.pin,
            seed_text=payload.seed_text,
            do_sync=payload.sync,
        )
        _CONNECT_JOBS[job_id] = {"status": "done", "result": _serialize_connect(result), "error": None}
    except Exception as exc:  # noqa: BLE001 — surfaced to the client via the job
        _CONNECT_JOBS[job_id] = {"status": "error", "result": None, "error": str(exc)}


@app.post("/api/connect", status_code=202)
async def create_connect(payload: ConnectPayload) -> dict[str, object]:
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

    job_id = uuid.uuid4().hex
    _CONNECT_JOBS[job_id] = {"status": "running", "result": None, "error": None}
    asyncio.get_event_loop().create_task(_run_connect_job(job_id, tribunal_cfg, payload))
    return {"job_id": job_id, "status": "running"}


@app.get("/api/connect/{job_id}")
async def get_connect(job_id: str) -> dict[str, object]:
    """Poll a connect job started by POST /api/connect."""
    job = _CONNECT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job não encontrado")
    return job


@app.get("/api/prazos")
async def get_prazos() -> dict[str, object]:
    """Deadline agenda: pending prazos across the acervo, soonest first."""
    return {"prazos": [v.to_dict() for v in list_prazos()]}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Render the local operator UI."""
    return _INDEX_PATH.read_text(encoding="utf-8")


@app.post("/api/demo-runs")
async def create_demo_run(payload: DemoRunPayload) -> dict[str, object]:
    """Run the demo pipeline from a browser request."""
    request = WebDemoRunRequest(
        numero_cnj=payload.numero_cnj.strip(),
        tipo=payload.tipo,
        tribunal=payload.tribunal.strip() or "tjmg",
        source=payload.source,
        modo=payload.modo,
        out_root=Path(payload.out_root),
        thesis=payload.thesis.strip() if payload.thesis else None,
        instructions=payload.instructions,
        cloud=payload.cloud,
        skip_review=payload.skip_review,
        use_cache=payload.use_cache,
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
    }
