"""FastAPI app for the local Juris pilot UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from juris import __version__
from juris.web.demo_service import DemoRunError, WebDemoRunRequest, execute_demo_run

app = FastAPI(
    title="Juris Web",
    version=__version__,
    description="Local browser UI for the Juris pilot demo workflow.",
)

_STATIC_DIR = Path(__file__).with_name("static")
_INDEX_PATH = _STATIC_DIR / "index.html"
_ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver", "testclient"}


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


def _require_local_request(request: Request) -> None:
    """Fail closed if the local-only web UI is reached through a non-local host."""
    host_header = (request.headers.get("host") or "").split(":", 1)[0].lower()
    client_host = (request.client.host if request.client else "").lower()
    if host_header and host_header not in _ALLOWED_LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Juris web local só aceita requests locais")
    if client_host and client_host not in _ALLOWED_LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Juris web local só aceita requests locais")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for the local web UI."""
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Render the local operator UI."""
    return _INDEX_PATH.read_text(encoding="utf-8")


@app.post("/api/demo-runs")
async def create_demo_run(request: Request, payload: DemoRunPayload) -> dict[str, object]:
    """Run the demo pipeline from a browser request."""
    _require_local_request(request)
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
