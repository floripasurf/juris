"""Cloud-side FastAPI orchestrator."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from juris import __version__
from juris.config import get_settings
from juris.core.observability import setup_logging

app = FastAPI(
    title="Juris API",
    version=__version__,
    description="Brazilian Legal AI — orchestrator API",
)


@app.on_event("startup")
async def startup() -> None:
    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_output=not settings.is_dev)


@app.get("/health")
async def health() -> JSONResponse:
    """Health check endpoint with dependency status."""
    # TODO: Check postgres, qdrant, redis connectivity
    return JSONResponse({"status": "ok", "version": __version__})
