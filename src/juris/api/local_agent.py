"""Lawyer-side local agent — the token-holding half of the split-trust (ADR-0015).

Runs on the lawyer's machine, where the A3 token is plugged in. The multi-tenant
orchestrator forwards token operations here over authenticated WebSockets:

* ``/ws/sign`` — PAdES signing (wired to :class:`InProcessSigningService`).
* ``/health`` — liveness + token/cert status.

The PIN is resolved locally (``_default_pin_resolver``) and never travels from the
orchestrator. ``/ws/mni`` (read operations) is the next endpoint on this contract.
"""
from __future__ import annotations

import base64
import os
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from juris.api.ws_schemas import HealthResponse, SignRequest, SignResponse
from juris.core.observability import get_logger

if TYPE_CHECKING:
    from juris.signing.service import SigningService

logger = get_logger(__name__)

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


def agent_signer() -> SigningService:
    """The agent's signing service — InProcess (token is local here). Overridable in tests."""
    from juris.signing.service import InProcessSigningService

    return InProcessSigningService()


def _default_pin_resolver() -> str:
    """Resolve the A3 PIN locally at the agent — never sent by the orchestrator.

    Reads ``$JURIS_AGENT_PIN`` (set on the lawyer's machine). A production agent
    would prompt interactively or read the OS keychain; the security property is
    that the PIN is resolved *here*, where the token lives.
    """
    pin = os.environ.get("JURIS_AGENT_PIN")
    if not pin:
        msg = "PIN do token não disponível no agente (defina JURIS_AGENT_PIN)."
        raise RuntimeError(msg)
    return pin


def handle_sign_request(
    request: SignRequest,
    service: SigningService,
    *,
    pin_resolver: Callable[[], str],
) -> SignResponse:
    """Sign the request's PDF with the local token; map the result/error.

    The PIN is resolved *locally* via ``pin_resolver`` (split-trust). Audit logs
    carry only non-sensitive metadata — never the PIN or the document bytes.
    """
    try:
        pdf_bytes = base64.b64decode(request.pdf_bytes_b64)
        pin = pin_resolver()
        result = service.sign_pdf(pdf_bytes, pin=pin, field_name=request.field_name)
    except Exception as exc:  # noqa: BLE001 — surfaced to the orchestrator as a typed error
        logger.warning(
            "agent_sign_failed",
            request_id=request.request_id,
            tenant_id=request.tenant_id,
            error=str(exc),
        )
        return SignResponse(request_id=request.request_id, success=False, error=str(exc))

    logger.info(
        "agent_sign_ok",
        request_id=request.request_id,
        tenant_id=request.tenant_id,
        signer_cpf=result.signer_cpf,  # who signed — auditable, not secret
        signed_pdf_hash=result.signed_pdf_hash,
    )
    return SignResponse(
        request_id=request.request_id,
        success=True,
        signed_pdf_b64=base64.b64encode(result.signed_pdf).decode("ascii"),
        signer_name=result.signer_name,
        signer_cpf=result.signer_cpf,
        signed_pdf_hash=result.signed_pdf_hash,
        signed_at=result.timestamp,
        cert_valid_until=result.cert_valid_until,
    )


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
    """WebSocket endpoint for signing requests (token-authenticated).

    Protocol: client connects with ``?token=``, sends a ``SignRequest`` JSON, the
    agent signs locally and replies with a ``SignResponse`` JSON; repeat or close.
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

            response = handle_sign_request(
                request, agent_signer(), pin_resolver=_default_pin_resolver
            )
            await ws.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        pass
