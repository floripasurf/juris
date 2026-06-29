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
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from juris.api.ws_schemas import AgentRequest, AgentResponse, HealthResponse, SignRequest, SignResponse
from juris.core.observability import get_logger

if TYPE_CHECKING:
    from juris.mni.service import MNIReadService
    from juris.mni.tribunais import TribunalConfig
    from juris.signing.service import SigningService

logger = get_logger(__name__)

_LOCAL_AGENT_HOST = "127.0.0.1"


@lru_cache(maxsize=1)
def _resolve_signing_token() -> str:
    """The agent's auth token — ``$JURIS_AGENT_TOKEN`` (paired with the orchestrator's
    ``JURIS_LOCAL_AGENT_TOKEN``) or a random dev token when unset."""
    return os.environ.get("JURIS_AGENT_TOKEN") or secrets.token_urlsafe(32)

app = FastAPI(
    title="Juris Local Agent",
    version="0.1.0",
    description="Lawyer-side local agent — signing + token management",
)


def get_signing_token() -> str:
    """Return the local signing token for authenticated clients."""
    return _resolve_signing_token()


def agent_signer() -> SigningService:
    """The agent's signing service — InProcess (token is local here). Overridable in tests."""
    from juris.signing.service import InProcessSigningService

    return InProcessSigningService()


def agent_mni_service() -> MNIReadService:
    """The agent's MNI read service — InProcess (token is local here). Overridable in tests."""
    from juris.mni.service import InProcessMNIReadService

    return InProcessMNIReadService()


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


def _default_credentials_resolver() -> tuple[str, str, str]:
    """Resolve the lawyer's PJe credentials + token PIN locally at the agent.

    Reads ``$JURIS_AGENT_CPF`` / ``$JURIS_AGENT_SENHA`` / ``$JURIS_AGENT_PIN`` (set
    on the lawyer's machine). The orchestrator never sends these — split-trust.
    """
    cpf = os.environ.get("JURIS_AGENT_CPF")
    senha = os.environ.get("JURIS_AGENT_SENHA")
    pin = os.environ.get("JURIS_AGENT_PIN")
    if not (cpf and senha and pin):
        msg = "credenciais do advogado ausentes no agente (JURIS_AGENT_CPF/SENHA/PIN)."
        raise RuntimeError(msg)
    return cpf, senha, pin


def handle_mni_request(
    request: AgentRequest,
    service: MNIReadService,
    *,
    credentials_resolver: Callable[[], tuple[str, str, str]],
    tribunal_resolver: Callable[[str], TribunalConfig],
) -> AgentResponse:
    """Run an MNI read with locally-resolved credentials; serialise the result.

    Dispatches on ``operation`` (``mni.consultar_processo`` / ``mni.consultar_avisos``).
    Credentials are resolved *here* (never on the wire); audit logs omit them.
    """
    from pydantic import TypeAdapter

    from juris.mni.operations.intimacoes import AvisosResult
    from juris.mni.parsers.processo import ProcessoDomain

    try:
        cpf, senha, pin = credentials_resolver()
        tribunal_cfg = tribunal_resolver(str(request.payload["tribunal_id"]))
        op = request.operation
        if op == "mni.consultar_processo":
            processo = service.consultar_processo(
                str(request.payload["numero_cnj"]),
                tribunal_cfg,
                cpf,
                senha,
                token_pin=pin,
                com_documentos=bool(request.payload.get("com_documentos", False)),
            )
            payload = TypeAdapter(ProcessoDomain).dump_python(processo, mode="json")
        elif op == "mni.consultar_avisos":
            avisos = service.consultar_avisos(tribunal_cfg, cpf, senha, token_pin=pin)
            payload = TypeAdapter(AvisosResult).dump_python(avisos, mode="json")
        else:
            msg = f"operação MNI desconhecida: {op}"
            return AgentResponse(request_id=request.request_id, success=False, error=msg)
    except Exception as exc:  # noqa: BLE001 — surfaced to the orchestrator as a typed error
        logger.warning(
            "agent_mni_failed",
            request_id=request.request_id,
            tenant_id=request.tenant_id,
            operation=request.operation,
            error=str(exc),
        )
        return AgentResponse(request_id=request.request_id, success=False, error=str(exc))

    logger.info(
        "agent_mni_ok",
        request_id=request.request_id,
        tenant_id=request.tenant_id,
        operation=request.operation,
    )
    return AgentResponse(request_id=request.request_id, success=True, payload=payload)


def validate_local_agent_host(host: str) -> str:
    """Only allow binding the local agent to localhost."""
    if host == "localhost":
        return _LOCAL_AGENT_HOST
    if host != _LOCAL_AGENT_HOST:
        msg = f"Local agent must bind to {_LOCAL_AGENT_HOST}, got {host}"
        raise ValueError(msg)
    return host


@dataclass(frozen=True, slots=True)
class TokenStatus:
    """Real readiness of the A3 token at the agent."""

    connected: bool
    cert_valid_until: date | None


def _default_token_probe() -> TokenStatus:
    """Best-effort read of the connected token's cert (no PIN needed). Errors ⇒ absent."""
    try:
        from juris.config import get_settings
        from juris.mni.token import extract_token_material

        material = extract_token_material(get_settings().pkcs11_module)
        until = date.fromisoformat(material.not_valid_after) if material.not_valid_after else None
        return TokenStatus(connected=True, cert_valid_until=until)
    except Exception:  # noqa: BLE001 — no token / unreadable ⇒ report not-ready, never crash /health
        return TokenStatus(connected=False, cert_valid_until=None)


def agent_health(*, token_probe: Callable[[], TokenStatus] | None = None) -> HealthResponse:
    """Build the agent's real readiness — token connectivity, cert validity, version."""
    from juris import __version__

    status = (token_probe or _default_token_probe)()
    return HealthResponse(
        status="ok",
        token_connected=status.connected,
        cert_valid_until=status.cert_valid_until,
        version=__version__,
    )


@app.get("/health")
async def health() -> HealthResponse:
    """Health check — reports real token connectivity, cert validity, and version."""
    return agent_health()


@app.websocket("/ws/sign")
async def signing_socket(ws: WebSocket) -> None:
    """WebSocket endpoint for signing requests (token-authenticated).

    Protocol: client connects with ``?token=``, sends a ``SignRequest`` JSON, the
    agent signs locally and replies with a ``SignResponse`` JSON; repeat or close.
    """
    token = ws.query_params.get("token")
    if token is None or not secrets.compare_digest(token, get_signing_token()):
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


@app.websocket("/ws/mni")
async def mni_socket(ws: WebSocket) -> None:
    """WebSocket endpoint for MNI read operations (token-authenticated).

    Client sends an ``AgentRequest`` (operation + params); the agent resolves the
    lawyer's credentials locally, runs the mTLS read, and replies with an
    ``AgentResponse`` carrying the serialised result.
    """
    token = ws.query_params.get("token")
    if token is None or not secrets.compare_digest(token, get_signing_token()):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()

    from juris.mni.tribunais import get_tribunal

    try:
        while True:
            data = await ws.receive_text()
            try:
                request = AgentRequest.model_validate_json(data)
            except Exception as e:  # noqa: BLE001 — malformed input → typed error reply
                await ws.send_text(
                    AgentResponse(
                        request_id="unknown", success=False, error=f"Invalid request: {e}"
                    ).model_dump_json()
                )
                continue
            response = handle_mni_request(
                request,
                agent_mni_service(),
                credentials_resolver=_default_credentials_resolver,
                tribunal_resolver=get_tribunal,
            )
            await ws.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        pass
