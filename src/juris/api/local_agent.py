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
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ValidationError

from juris.api.ws_schemas import AgentRequest, AgentResponse, HealthResponse, SignRequest, SignResponse
from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text

if TYPE_CHECKING:
    from juris.mni.service import MNIReadService
    from juris.mni.tribunais import TribunalConfig
    from juris.signing.filing_service import FilingService
    from juris.signing.service import SigningService

logger = get_logger(__name__)

_LOCAL_AGENT_HOST = "127.0.0.1"
_BROWSER_PAIRING_ORIGINS = {
    "https://causia.com.br",
    "https://app.causia.com.br",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}
_SIGN_ERROR = "Falha ao assinar no agente local. Verifique token e PIN no agente."
_MNI_ERROR = "Falha ao consultar MNI no agente local. Verifique credenciais, token e tribunal."
_INVALID_REQUEST_ERROR = "Requisição inválida para o agente local."


def _deid_reads_enabled() -> bool:
    """ADR-0016: redact processo PII at the agent BEFORE the read result crosses to
    the cloud (the re-id map stays local, in :mod:`juris.api.reid_store`).

    Off by default. In Phase-2 SaaS, the final petition is rendered/signed on the
    AGENT side; the filing handler re-identifies the draft from this local map
    immediately before render/sign/file, so the cloud console can stay
    placeholder-bearing without producing a placeholder-bearing PDF.
    """
    return os.environ.get("JURIS_AGENT_DEID_READS", "").strip().lower() in {"1", "true", "yes"}
_AGENT_PROCESSING_ERROR = "Falha ao processar requisição no agente local."


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
_RELAY_THREADS: dict[str, threading.Thread] = {}


class RelayPairingPayload(BaseModel):
    """Browser -> local-agent pairing payload. Token stays on loopback."""

    relay_url: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    agent_token: str = Field(min_length=1)


class AgentCredentialsPayload(BaseModel):
    """Local browser form -> local-agent credentials. Never sent to the cloud."""

    cpf: str = Field(min_length=11, max_length=18)
    senha: str = Field(min_length=1, max_length=256)
    pin: str = Field(min_length=1, max_length=128)
    tribunal: str = Field(default="tjmg", min_length=2, max_length=32)


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


def _cors_headers(origin: str | None) -> dict[str, str]:
    if origin is None or not _is_allowed_browser_origin(origin):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Allow-Private-Network": "true",
        "Vary": "Origin",
    }


def _origin_is_loopback(origin: str | None) -> bool:
    if origin is None:
        return False
    from urllib.parse import urlparse

    return (urlparse(origin).hostname or "") in _LOOPBACK_HOSTS


def _is_allowed_browser_origin(origin: str | None) -> bool:
    return origin in _BROWSER_PAIRING_ORIGINS or _origin_is_loopback(origin)


def _assert_browser_agent_request(request: Request, *, allow_cloud_origin: bool) -> str | None:
    host = request.headers.get("host", "").split(":")[0]
    client_host = request.client.host if request.client else ""
    if host not in _LOOPBACK_HOSTS or client_host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="agente local apenas por loopback")
    origin = request.headers.get("origin")
    origin_allowed = (
        origin is None
        or _origin_is_loopback(origin)
        or (allow_cloud_origin and origin in _BROWSER_PAIRING_ORIGINS)
    )
    if not origin_allowed:
        raise HTTPException(status_code=403, detail="origem não autorizada para o agente local")
    return origin


def _assert_browser_pairing_request(request: Request) -> str | None:
    try:
        return _assert_browser_agent_request(request, allow_cloud_origin=True)
    except HTTPException as exc:
        if exc.detail == "agente local apenas por loopback":
            raise HTTPException(status_code=403, detail="agent pairing apenas por loopback") from exc
        raise HTTPException(status_code=403, detail="origem não autorizada para pareamento do agente") from exc


def _assert_local_setup_request(request: Request) -> None:
    _assert_browser_agent_request(request, allow_cloud_origin=False)


def _assert_credentials_request(request: Request) -> str | None:
    try:
        return _assert_browser_agent_request(request, allow_cloud_origin=True)
    except HTTPException as exc:
        if exc.detail == "agente local apenas por loopback":
            raise HTTPException(status_code=403, detail="configuração do agente apenas por loopback") from exc
        raise HTTPException(status_code=403, detail="origem não autorizada para credenciais locais") from exc


def _start_relay_pairing(payload: RelayPairingPayload) -> None:
    from juris.web.auth import validate_tenant_id

    tenant_id = validate_tenant_id(payload.tenant_id)

    def _run() -> None:
        try:
            run_relay_agent(payload.relay_url, payload.agent_token, tenant_id)
        except Exception as exc:  # noqa: BLE001 - local background task logs only sanitized detail
            logger.warning(
                "agent_relay_pairing_stopped",
                tenant_id=tenant_id,
                error=safe_error_text(exc),
                exception_type=exc.__class__.__name__,
            )

    thread = threading.Thread(target=_run, name=f"causia-relay-{tenant_id}", daemon=True)
    _RELAY_THREADS[tenant_id] = thread
    thread.start()


def _normalize_cpf_for_storage(cpf: str) -> str:
    digits = "".join(ch for ch in cpf if ch.isdigit())
    if len(digits) != 11:
        raise ValueError("CPF deve ter 11 dígitos.")
    return digits


def _normalize_tribunal_for_storage(tribunal: str) -> str:
    normalized = tribunal.strip().lower()
    if not normalized or not all(ch.isalnum() or ch in {"_", "-"} for ch in normalized):
        raise ValueError("Tribunal inválido.")
    return normalized


def _require_non_blank_secret(value: str, label: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{label} é obrigatório.")
    return value


def configure_local_credentials(payload: AgentCredentialsPayload) -> None:
    """Persist local credentials in the agent's secure local store."""
    from juris.core.credentials import store_credential

    cpf = _normalize_cpf_for_storage(payload.cpf)
    tribunal = _normalize_tribunal_for_storage(payload.tribunal)
    senha = _require_non_blank_secret(payload.senha, "Senha PJe")
    pin = _require_non_blank_secret(payload.pin, "PIN do token A3")
    store_credential("agent_tribunal", tribunal)
    store_credential("agent_cpf", cpf)
    store_credential(f"mni_{tribunal}_{cpf}", senha)
    store_credential("token_pin", pin)
    logger.info("agent_credentials_configured", tribunal=tribunal)


def local_credentials_configured() -> bool:
    """Report whether the agent can resolve CPF/PJe/PIN locally without exposing them."""
    try:
        _default_credentials_resolver()
    except Exception:  # noqa: BLE001 - readiness endpoint must never leak internal credential state
        return False
    return True


async def _credentials_payload_from_request(request: Request) -> AgentCredentialsPayload:
    from urllib.parse import parse_qs

    try:
        if "application/json" in request.headers.get("content-type", ""):
            raw = await request.json()
        else:
            parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
            raw = {key: values[-1] for key, values in parsed.items()}
        return AgentCredentialsPayload.model_validate(raw)
    except (UnicodeDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Informe CPF, senha PJe e PIN do token.") from exc


def _local_setup_html() -> str:
    return """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Causia Agent</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f7f5f0; color: #22252a; }
    main { max-width: 520px; margin: 48px auto; padding: 0 20px; }
    h1 { margin: 0 0 10px; font-size: 28px; }
    p { color: #5d626b; line-height: 1.5; }
    form { display: grid; gap: 14px; margin-top: 24px; }
    label { display: grid; gap: 6px; font-weight: 650; }
    input { border: 1px solid #d6d0c7; border-radius: 4px; padding: 11px 12px; font: inherit; }
    a { color: #6f2232; font-weight: 700; }
    button {
      border: 1px solid #6f2232;
      border-radius: 4px;
      background: #6f2232;
      color: white;
      padding: 11px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    #status { min-height: 22px; font-weight: 650; }
    .ok { color: #1f6b3a; }
    .err { color: #9b1c1c; }
  </style>
</head>
<body>
  <main>
    <h1>Causia Agent</h1>
    <p>Informe as credenciais neste computador. Elas ficam no agente local e não são enviadas ao servidor da Causia.</p>
    <form id="credentials-form">
      <label>CPF do advogado
        <input name="cpf" inputmode="numeric" autocomplete="username" required />
      </label>
      <label>Senha PJe
        <input name="senha" type="password" autocomplete="current-password" required />
      </label>
      <label>PIN do token A3
        <input name="pin" type="password" autocomplete="off" required />
      </label>
      <label>Tribunal
        <input name="tribunal" value="tjmg" autocomplete="off" required />
      </label>
      <button type="submit">Salvar neste computador</button>
      <p id="status" role="status" aria-live="polite"></p>
    </form>
    <p><a href="https://causia.com.br/">Voltar ao Causia</a></p>
  </main>
  <script>
    const form = document.querySelector("#credentials-form");
    const status = document.querySelector("#status");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      status.className = "";
      status.textContent = "Salvando...";
      const body = Object.fromEntries(new FormData(form).entries());
      try {
        const response = await fetch("/credentials", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Falha ao salvar.");
        form.reset();
        form.tribunal.value = body.tribunal || "tjmg";
        status.className = "ok";
        status.textContent = data.message || "Credenciais salvas neste computador.";
      } catch (error) {
        status.className = "err";
        status.textContent = error.message;
      }
    });
  </script>
</body>
</html>"""


@app.options("/pair-relay")
async def pair_relay_options(request: Request) -> Response:
    origin = _assert_browser_pairing_request(request)
    return Response(status_code=204, headers=_cors_headers(origin))


@app.post("/pair-relay", status_code=202)
async def pair_relay_from_browser(payload: RelayPairingPayload, request: Request) -> Response:
    """Pair this local agent with a Causia trial without requiring terminal usage.

    The public web page obtains a one-time relay token from the orchestrator and
    posts it to this loopback endpoint. The token never goes in a URL and the
    local agent then dials out to the cloud relay.
    """
    origin = _assert_browser_pairing_request(request)
    _start_relay_pairing(payload)
    return Response(status_code=202, headers=_cors_headers(origin))


@app.get("/setup")
async def local_setup_page(request: Request) -> HTMLResponse:
    """Local-only setup page for lawyer credentials."""
    _assert_local_setup_request(request)
    return HTMLResponse(
        _local_setup_html(),
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/credentials")
async def save_local_credentials(request: Request) -> Response:
    """Save CPF/PJe/PIN locally through the local agent's browser page."""
    origin = _assert_credentials_request(request)
    payload = await _credentials_payload_from_request(request)
    try:
        configure_local_credentials(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        '{"status":"ok","message":"Credenciais salvas no agente local."}',
        media_type="application/json",
        headers=_cors_headers(origin),
    )


@app.options("/credentials")
async def credentials_options(request: Request) -> Response:
    origin = _assert_credentials_request(request)
    return Response(status_code=204, headers=_cors_headers(origin))


@app.get("/credentials/status")
async def local_credentials_status(request: Request) -> Response:
    """Return only readiness, never the credential values."""
    origin = _assert_credentials_request(request)
    configured = "true" if local_credentials_configured() else "false"
    return Response(
        f'{{"configured":{configured}}}',
        media_type="application/json",
        headers=_cors_headers(origin),
    )


@app.options("/credentials/status")
async def credentials_status_options(request: Request) -> Response:
    origin = _assert_credentials_request(request)
    return Response(status_code=204, headers=_cors_headers(origin))


def _default_pin_resolver() -> str:
    """Resolve the A3 PIN locally at the agent — never sent by the orchestrator.

    Reads ``$JURIS_AGENT_PIN`` first, then the secure local store populated by
    ``/setup``. The security property is that the PIN is resolved *here*, where
    the token lives.
    """
    pin = os.environ.get("JURIS_AGENT_PIN")
    if not pin:
        from juris.core.credentials import get_credential

        pin = get_credential("token_pin")
    if not pin or not pin.strip():
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
            error=safe_error_text(exc),
        )
        return SignResponse(request_id=request.request_id, success=False, error=_SIGN_ERROR)

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

    Reads env vars first, then the secure local store populated by ``/setup``.
    The orchestrator never sends these — split-trust.
    """
    cpf = os.environ.get("JURIS_AGENT_CPF")
    senha = os.environ.get("JURIS_AGENT_SENHA")
    pin = os.environ.get("JURIS_AGENT_PIN")
    from juris.core.credentials import get_credential

    cpf = cpf or get_credential("agent_cpf")
    tribunal_raw = os.environ.get("JURIS_AGENT_TRIBUNAL") or get_credential("agent_tribunal") or "tjmg"
    try:
        cpf_key = _normalize_cpf_for_storage(cpf or "")
        tribunal = _normalize_tribunal_for_storage(tribunal_raw)
    except ValueError as exc:
        raise RuntimeError("credenciais do advogado inválidas no agente.") from exc

    senha = senha or get_credential(f"mni_{tribunal}_{cpf_key}")
    pin = pin or get_credential("token_pin")
    if not (cpf_key and senha and senha.strip() and pin and pin.strip()):
        msg = "credenciais do advogado ausentes no agente (JURIS_AGENT_CPF/SENHA/PIN)."
        raise RuntimeError(msg)
    return cpf_key, senha, pin


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
            # Split-trust: in de-id mode the processo is redacted HERE, and the
            # re-id map stays on the agent — the SaaS cloud never sees raw names/CPFs.
            if _deid_reads_enabled():
                from juris.api.reid_store import save_reid_map
                from juris.mni.deid_processo import deidentify_processo

                processo, reid_map = deidentify_processo(processo)
                save_reid_map(request.tenant_id, str(request.payload["numero_cnj"]), reid_map)
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
            error=safe_error_text(exc),
        )
        return AgentResponse(request_id=request.request_id, success=False, error=_MNI_ERROR)

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


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", ""}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _allow_query_token() -> bool:
    """Temporary compatibility switch for old local clients that used ``?token=``."""
    return _env_flag("JURIS_AGENT_ALLOW_QUERY_TOKEN")


def _ws_authorized(ws: WebSocket) -> bool:
    """Authorize a WS handshake: non-foreign Origin (+ loopback Host) and a valid token.

    Only browsers send an ``Origin`` header — that's the DNS-rebinding / CSRF surface
    against the loopback-bound agent. When Origin is present it (and the Host) MUST be
    loopback, so a malicious page the lawyer has open can't reach the agent even if it
    steals the token. A legit orchestrator client sends no Origin and is unaffected.
    The token comes from the ``x-agent-token`` header, so it never lands in an
    access-logged URL. Legacy ``?token=`` is rejected unless explicitly re-enabled
    with ``JURIS_AGENT_ALLOW_QUERY_TOKEN=1`` during migration.
    """
    origin = ws.headers.get("origin")
    if origin is not None:
        from urllib.parse import urlparse

        if (urlparse(origin).hostname or "") not in _LOOPBACK_HOSTS:
            return False
        if ws.headers.get("host", "").split(":")[0] not in _LOOPBACK_HOSTS:
            return False
    token = ws.headers.get("x-agent-token")
    if token is None and _allow_query_token():
        token = ws.query_params.get("token")
    return token is not None and secrets.compare_digest(token, get_signing_token())


@app.websocket("/ws/sign")
async def signing_socket(ws: WebSocket) -> None:
    """WebSocket endpoint for signing requests (token-authenticated).

    Protocol: client connects (token in the ``x-agent-token`` header), sends a
    ``SignRequest`` JSON, the agent signs locally and replies with a ``SignResponse``
    JSON; repeat or close.
    """
    if not _ws_authorized(ws):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()

    try:
        while True:
            data = await ws.receive_text()
            try:
                request = SignRequest.model_validate_json(data)
            except Exception:  # noqa: BLE001
                response = SignResponse(
                    request_id="unknown",
                    success=False,
                    error=_INVALID_REQUEST_ERROR,
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
    if not _ws_authorized(ws):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()

    from juris.mni.tribunais import get_tribunal

    try:
        while True:
            data = await ws.receive_text()
            try:
                request = AgentRequest.model_validate_json(data)
            except Exception:  # noqa: BLE001 — malformed input → typed error reply
                await ws.send_text(
                    AgentResponse(
                        request_id="unknown", success=False, error=_INVALID_REQUEST_ERROR
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


def agent_filing_service() -> FilingService:
    """The agent's filing service — InProcess (token is local here). Overridable in tests."""
    from juris.signing.filing_service import InProcessFilingService

    return InProcessFilingService()


@app.websocket("/ws/file")
async def filing_socket(ws: WebSocket) -> None:
    """WebSocket endpoint for remote filing (token-authenticated).

    The agent runs the whole pipeline (render → preflight → sign → peticionar) with
    locally-resolved credentials, and replies with the chain-of-custody proof.
    """
    if not _ws_authorized(ws):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()

    from juris.signing.filing_service import handle_file_request

    try:
        while True:
            data = await ws.receive_text()
            try:
                request = AgentRequest.model_validate_json(data)
            except Exception:  # noqa: BLE001 — malformed input → typed error reply
                await ws.send_text(
                    AgentResponse(
                        request_id="unknown", success=False, error=_INVALID_REQUEST_ERROR
                    ).model_dump_json()
                )
                continue
            response = await handle_file_request(
                request, agent_filing_service(), credentials_resolver=_default_credentials_resolver
            )
            await ws.send_text(response.model_dump_json())
    except WebSocketDisconnect:
        pass


async def dispatch_agent_request(request: AgentRequest) -> AgentResponse:
    """Route a relayed ``AgentRequest`` to the right local handler (agent side).

    Used by the reverse channel: the orchestrator forwards a request over the dialed-in
    connection and the agent runs it locally (credentials resolved here). ``file``
    covers signing too — the whole pipeline runs at the agent.
    """
    from juris.mni.tribunais import get_tribunal

    op = request.operation
    if op == "health":
        health = agent_health()
        return AgentResponse(
            request_id=request.request_id,
            success=True,
            payload=health.model_dump(mode="json"),
        )
    if op == "file":
        from juris.signing.filing_service import handle_file_request

        return await handle_file_request(
            request, agent_filing_service(), credentials_resolver=_default_credentials_resolver
        )
    if op == "sign":
        sign_request = SignRequest.model_validate(
            {"request_id": request.request_id, "tenant_id": request.tenant_id, **request.payload}
        )
        sign_response = handle_sign_request(sign_request, agent_signer(), pin_resolver=_default_pin_resolver)
        payload = (
            sign_response.model_dump(mode="json", exclude={"request_id", "success", "error"})
            if sign_response.success
            else None
        )
        return AgentResponse(
            request_id=request.request_id,
            success=sign_response.success,
            payload=payload,
            error=sign_response.error,
        )
    if op.startswith("mni"):
        return handle_mni_request(
            request,
            agent_mni_service(),
            credentials_resolver=_default_credentials_resolver,
            tribunal_resolver=get_tribunal,
        )
    return AgentResponse(
        request_id=request.request_id, success=False, error=f"operação não suportada no relay: {op}"
    )


def run_relay_agent(
    url: str,
    token: str,
    tenant_id: str,
    *,
    dispatch: Callable[[AgentRequest], Coroutine[object, object, AgentResponse]] | None = None,
) -> None:
    """Agent-side dialer: connect OUT to the orchestrator's relay and serve requests.

    Blocking. The agent dials the cloud (so no inbound port / NAT hole is needed), then
    for each forwarded ``AgentRequest`` runs it locally and sends back the
    ``AgentResponse``. Reconnection/backoff is the caller's concern.
    """
    import asyncio
    from urllib.parse import urlencode

    from websockets.sync.client import connect

    from juris.web.auth import validate_tenant_id

    handler = dispatch or dispatch_agent_request
    tenant_id = validate_tenant_id(tenant_id)
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}{urlencode({'tenant': tenant_id})}"
    with connect(full_url, additional_headers={"x-agent-token": token}) as ws:
        for raw in ws:  # each message is a forwarded AgentRequest
            text = raw if isinstance(raw, str) else raw.decode()
            response: AgentResponse
            try:
                request = AgentRequest.model_validate_json(text)
                response = asyncio.run(handler(request))
            except Exception:  # noqa: BLE001 — typed error back to the orchestrator
                response = AgentResponse(request_id="unknown", success=False, error=_AGENT_PROCESSING_ERROR)
            ws.send(response.model_dump_json())
