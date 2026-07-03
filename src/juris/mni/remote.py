"""Remote MNI read service — the split-trust client (ADR-0015, Phase 2).

The A3 token (and the lawyer's PJe credentials + PIN) live on the lawyer's
machine. :class:`RemoteMNIReadService` forwards only the *operation parameters*
(``numero_cnj``, ``tribunal_id``) to the local agent over an authenticated
transport; the agent fills in the credentials locally and runs the mTLS read.
**No credential ever travels from the orchestrator** — that is the whole point.

Reads are idempotent, so the transport may retry briefly (unlike signing).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from pydantic import TypeAdapter

from juris.api.ws_schemas import AgentRequest, AgentResponse
from juris.mni.operations.intimacoes import AvisosResult
from juris.mni.parsers.processo import ProcessoDomain
from juris.mni.service import MNIReadService

if TYPE_CHECKING:
    from juris.mni.tribunais import TribunalConfig

_PROCESSO_ADAPTER = TypeAdapter(ProcessoDomain)
_AVISOS_ADAPTER = TypeAdapter(AvisosResult)


class AgentTransport(Protocol):
    """Carries an :class:`AgentRequest` to the local agent and returns its reply."""

    def send(self, request: AgentRequest) -> AgentResponse: ...


class WebSocketAgentTransport:
    """Sync WebSocket transport to the agent's ``/ws/mni`` (token-authenticated).

    Reads are idempotent, so a transient connection failure is retried a few times
    (a re-read is harmless). One connection per request.
    """

    def __init__(self, url: str, *, token: str, timeout: float = 30.0, retries: int = 2) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout
        self._retries = retries

    def send(self, request: AgentRequest) -> AgentResponse:
        from websockets.sync.client import connect

        headers = {"x-agent-token": self._token}  # token in a header, never the logged URL
        last_exc: Exception | None = None
        for _attempt in range(self._retries + 1):
            try:
                with connect(self._url, additional_headers=headers, open_timeout=self._timeout) as ws:
                    ws.send(request.model_dump_json())
                    raw = ws.recv(timeout=self._timeout)
                return AgentResponse.model_validate_json(raw)
            except (OSError, TimeoutError) as exc:  # transient → retry (idempotent read)
                last_exc = exc
        msg = f"agente local inacessível após {self._retries + 1} tentativas: {last_exc}"
        raise RuntimeError(msg) from last_exc


class RelayAgentTransport:
    """Sync transport through the orchestrator relay for NAT-friendly trials."""

    def __init__(self, tenant_id: str, *, timeout: float = 30.0) -> None:
        self._tenant_id = tenant_id
        self._timeout = timeout

    def send(self, request: AgentRequest) -> AgentResponse:
        from juris.api.relay import get_relay_hub

        return get_relay_hub().send_sync(self._tenant_id, request, timeout=self._timeout)


class RemoteMNIReadService(MNIReadService):
    """Reads MNI by forwarding to the lawyer's local agent (credentials stay remote)."""

    def __init__(self, transport: AgentTransport, *, tenant_id: str = "public") -> None:
        self._transport = transport
        self._tenant_id = tenant_id

    def _call(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        request = AgentRequest(
            request_id=uuid.uuid4().hex,
            tenant_id=self._tenant_id,
            operation=operation,
            payload=payload,
        )
        response = self._transport.send(request)
        if response.request_id != request.request_id:
            msg = (
                f"resposta MNI não correlaciona com o pedido "
                f"(esperado {request.request_id}, veio {response.request_id})"
            )
            raise RuntimeError(msg)
        if not response.success:
            raise RuntimeError(response.error or f"operação remota {operation} falhou")
        return response.payload or {}

    def consultar_processo(
        self,
        numero_cnj: str,
        tribunal_cfg: TribunalConfig,
        cpf: str,
        senha: str,
        *,
        token_pin: str | None = None,
        com_documentos: bool = False,
    ) -> ProcessoDomain:
        # cpf / senha / token_pin are deliberately NOT forwarded — the agent
        # resolves the lawyer's credentials locally (split-trust).
        payload = self._call(
            "mni.consultar_processo",
            {"numero_cnj": numero_cnj, "tribunal_id": tribunal_cfg.id, "com_documentos": com_documentos},
        )
        return _PROCESSO_ADAPTER.validate_python(payload)

    def consultar_avisos(
        self,
        tribunal_cfg: TribunalConfig,
        cpf: str,
        senha: str,
        *,
        token_pin: str | None = None,
    ) -> AvisosResult:
        payload = self._call("mni.consultar_avisos", {"tribunal_id": tribunal_cfg.id})
        return _AVISOS_ADAPTER.validate_python(payload)
