"""Lawyer-side local agent for signing operations.

Provides a WebSocket endpoint for remote signing requests and a health
check endpoint. In Sprint 11, the CLI calls PAdESSigner directly.
This agent defines the message protocol contract for Sprint 14+ multi-tenant SaaS.
"""
from __future__ import annotations

import secrets

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from juris.api.ws_schemas import HealthResponse, SignRequest, SignResponse

_SIGNING_TOKEN = secrets.token_urlsafe(32)
_LOCAL_AGENT_HOST = "127.0.0.1"

app = FastAPI(
    title="Juris Local Agent",
    version="0.1.0",
    description="Lawyer-side local agent — signing + token management",
)


def get_signing_token() -> str:
    """Return the local signing token for authenticated clients."""
    return _SIGNING_TOKEN


def validate_local_agent_host(host: str) -> str:
    """Only allow binding the local agent to localhost."""
    if host == "localhost":
        return _LOCAL_AGENT_HOST
    if host != _LOCAL_AGENT_HOST:
        msg = f"Local agent must bind to {_LOCAL_AGENT_HOST}, got {host}"
        raise ValueError(msg)
    return host


@app.get("/health")
async def health() -> HealthResponse:
    """Health check — reports token connectivity and cert status."""
    # In Sprint 11, this is a minimal implementation.
    # Sprint 14+ will check actual PKCS#11 token connectivity.
    return HealthResponse(
        status="ok",
        token_connected=False,  # Will be dynamic in Sprint 14+
    )


@app.websocket("/ws/sign")
async def signing_socket(ws: WebSocket) -> None:
    """WebSocket endpoint for signing requests.

    Protocol:
    1. Client connects
    2. Client sends SignRequest JSON
    3. Server responds with SignResponse JSON
    4. Repeat or close

    In Sprint 11, this is a skeleton that validates messages but
    returns an error response (no actual signer wired up).
    Sprint 14+ will wire this to PAdESSigner.
    """
    token = ws.query_params.get("token")
    if token is None or not secrets.compare_digest(token, _SIGNING_TOKEN):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()

    try:
        while True:
            data = await ws.receive_text()
            try:
                request = SignRequest.model_validate_json(data)
            except Exception as e:
                response = SignResponse(
                    request_id="unknown",
                    success=False,
                    error=f"Invalid request: {e}",
                )
                await ws.send_text(response.model_dump_json())
                continue

            # Sprint 11: skeleton — return not-implemented error
            # Sprint 14+: wire to PAdESSigner
            response = SignResponse(
                request_id=request.request_id,
                success=False,
                error="Signing not yet wired — use CLI 'juris file' in Sprint 11",
            )
            await ws.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        pass
