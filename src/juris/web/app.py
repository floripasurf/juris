"""FastAPI app for the local Juris pilot UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from juris import __version__
from juris.web.demo_service import DemoRunError, WebDemoRunRequest, execute_demo_run
from juris.web.processos_service import list_processos

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
    }
