"""Remote signing service — the split-trust client (ADR-0015, Phase 2).

The orchestrator (cloud) never touches the A3 token. :class:`RemoteSigningService`
forwards the unsigned PDF to the lawyer's local agent over an authenticated
transport; the agent signs with the token plugged into *its* machine and returns
the signed PDF. Crucially, the **PIN is never sent** — it is resolved at the agent,
so the cloud holds no token secret.

Swapping :class:`InProcessSigningService` for this is configuration (see
:func:`juris.signing.factory.get_signing_service`), not an orchestrator rewrite.
"""

from __future__ import annotations

import base64
import uuid
from typing import TYPE_CHECKING, Protocol

from juris.api.ws_schemas import SignRequest, SignResponse
from juris.signing.pades import SigningResult, _sha256_hex
from juris.signing.service import SigningService

if TYPE_CHECKING:
    pass


class SignTransport(Protocol):
    """Carries a :class:`SignRequest` to the local agent and returns its reply."""

    def send(self, request: SignRequest) -> SignResponse: ...


class WebSocketSignTransport:
    """Sync WebSocket transport to the local agent's ``/ws/sign`` (token-authenticated).

    Signing is **not idempotent** — this transport does **not** retry, so a partial
    failure never risks a double-signature. One connection per request.
    """

    def __init__(self, url: str, *, token: str, timeout: float = 30.0) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout

    def send(self, request: SignRequest) -> SignResponse:
        from websockets.sync.client import connect

        sep = "&" if "?" in self._url else "?"
        full_url = f"{self._url}{sep}token={self._token}"
        with connect(full_url, open_timeout=self._timeout) as ws:
            ws.send(request.model_dump_json())
            raw = ws.recv(timeout=self._timeout)
        return SignResponse.model_validate_json(raw)


class RemoteSigningService(SigningService):
    """Signs by forwarding to the lawyer's local agent (token stays remote)."""

    def __init__(self, transport: SignTransport, *, tenant_id: str = "public") -> None:
        self._transport = transport
        self._tenant_id = tenant_id

    def sign_pdf(
        self,
        pdf_bytes: bytes,
        *,
        pin: str,
        token_label: str | None = None,
        field_name: str = "AdvogadoSignature",
        use_timestamp: bool = False,
    ) -> SigningResult:
        # The PIN/token_label/use_timestamp are deliberately NOT forwarded: the
        # agent resolves the PIN locally (split-trust) and applies its own token
        # policy. We only ship the bytes to sign.
        request = SignRequest(
            request_id=uuid.uuid4().hex,
            tenant_id=self._tenant_id,
            pdf_bytes_b64=base64.b64encode(pdf_bytes).decode("ascii"),
            field_name=field_name,
        )
        response = self._transport.send(request)
        if response.request_id != request.request_id:
            msg = (
                f"resposta de assinatura não correlaciona com o pedido "
                f"(esperado {request.request_id}, veio {response.request_id})"
            )
            raise RuntimeError(msg)
        if not response.success:
            raise RuntimeError(response.error or "assinatura remota falhou")
        if response.signed_at is None or response.cert_valid_until is None:
            msg = "resposta de assinatura sem timestamp/validade do certificado"
            raise RuntimeError(msg)
        return SigningResult(
            signed_pdf=base64.b64decode(response.signed_pdf_b64 or ""),
            signer_name=response.signer_name or "",
            signer_cpf=response.signer_cpf or "",
            timestamp=response.signed_at,
            pdf_hash=_sha256_hex(pdf_bytes),
            signed_pdf_hash=response.signed_pdf_hash or "",
            cert_valid_until=response.cert_valid_until,
        )
