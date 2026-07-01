"""Filing service — the boundary for petitioning, co-located or remote (ADR-0015).

Filing needs the A3 token for **both** signing and (mTLS) peticionamento, so the
whole :class:`FilingOrchestrator` pipeline runs where the token lives:

* :class:`InProcessFilingService` — runs it here (Phase 1, CLI).
* :class:`RemoteFilingService` — forwards a :class:`FilingRequest` to the lawyer's
  agent over ``/ws/file`` (Phase 2). Credentials (cpf/senha/PIN) are resolved at the
  agent and never cross; the result comes back as the **chain-of-custody hashes**
  (the auditable proof) — the signed PDF and receipt stay at the agent.

``run_filing`` is the shared in-process body (used by the CLI and the agent).
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from juris.api.ws_schemas import AgentRequest, AgentResponse
from juris.signing.filing import ChainOfCustody, FilingRequest, FilingResult

if TYPE_CHECKING:
    from juris.mni.operations.peticionamento import FilingReceipt


async def run_filing(
    request: FilingRequest, *, pin: str | None, storage_root: Path | None = None
) -> FilingResult:
    """Build the in-process :class:`FilingOrchestrator` and run the pipeline.

    A dry-run that also skips preflight needs no token (mock signer); otherwise the
    A3 ``pin`` is required to open the signer.

    ``storage_root`` is the per-tenant ``~/.juris`` (audit chain + filing receipts land
    under it). Defaults to the shared home — co-located single-tenant. Multi-tenant
    callers MUST pass the tenant-scoped root so one firm's signed petitions and audit
    never commingle with another's.
    """
    from juris.mni.auth import AuthStrategy, PasswordAuth
    from juris.persistence.audit import AuditLog
    from juris.persistence.filing_receipt import FilingReceiptStore
    from juris.signing.filing import FilingOrchestrator

    juris_dir = storage_root or Path.home() / ".juris"
    audit = AuditLog(juris_dir / "audit.jsonl")
    receipt_store = FilingReceiptStore(juris_dir / "filings", audit)
    mni_auth = PasswordAuth(cpf=request.cpf, senha=request.senha)

    def mni_client_factory(tribunal_id: str, auth: AuthStrategy) -> object:
        from juris.mni.client import get_mni_client

        return get_mni_client(tribunal_id, auth)

    if request.dry_run and request.skip_preflight:
        from unittest.mock import MagicMock

        from juris.signing.pades import PAdESSigner

        orchestrator = FilingOrchestrator(
            signer=MagicMock(spec=PAdESSigner),
            audit=audit,
            receipt_store=receipt_store,
            mni_client_factory=mni_client_factory,
            mni_auth=mni_auth,
        )
        return await orchestrator.file(request)

    if not pin:
        msg = "PIN do token é obrigatório para assinar/peticionar."
        raise RuntimeError(msg)

    from juris.signing.service import InProcessSigningService

    with InProcessSigningService().open_signer(pin=pin) as signer:
        orchestrator = FilingOrchestrator(
            signer=signer,
            audit=audit,
            receipt_store=receipt_store,
            mni_client_factory=mni_client_factory,
            mni_auth=mni_auth,
        )
        return await orchestrator.file(request)


class FilingService(ABC):
    """Files a petition with the lawyer's token, abstracting where it lives."""

    @abstractmethod
    async def file(self, request: FilingRequest, *, pin: str | None = None) -> FilingResult:
        """Render → preflight → sign → peticionar; return the :class:`FilingResult`."""
        ...


class InProcessFilingService(FilingService):
    """Files in the current process (Phase 1, co-located token).

    ``storage_root`` scopes the audit chain + filing receipts to one tenant.
    """

    def __init__(self, storage_root: Path | None = None) -> None:
        self._storage_root = storage_root

    async def file(self, request: FilingRequest, *, pin: str | None = None) -> FilingResult:
        return await run_filing(request, pin=pin, storage_root=self._storage_root)


def get_filing_service(tenant_id: str = "public", *, storage_root: Path | None = None) -> FilingService:
    """Return the configured :class:`FilingService` (InProcess or Remote by config).

    ``storage_root`` (the tenant's ``~/.juris``) isolates in-process receipts/audit;
    remote mode ignores it — the agent uses its own local storage.
    """
    from juris.api.agent_config import is_remote, tenant_agent_binding

    if is_remote():
        from juris.mni.remote import WebSocketAgentTransport  # same /ws transport, /ws/file

        binding = tenant_agent_binding(tenant_id)  # routes to THIS firm's agent
        transport = WebSocketAgentTransport(binding.base_url + "/ws/file", token=binding.token)
        return RemoteFilingService(transport, tenant_id=tenant_id)

    return InProcessFilingService(storage_root=storage_root)


# --- Remote (split-trust) -----------------------------------------------------


def _custody_to_payload(result: FilingResult) -> dict[str, object]:
    """The auditable proof + protocol metadata that crosses back.

    Hashes (chain of custody) + the receipt's protocol fields (numero, data,
    processo, status) — enough for the UI/audit, **never** the PDF or any secret.
    """
    coc = result.chain_of_custody
    rcpt = result.receipt
    return {
        "success": result.success,
        "error": result.error,
        "audit_entry_ids": list(result.audit_entry_ids),
        "chain_of_custody": (
            {
                "pdf_hash": coc.pdf_hash,
                "signed_pdf_hash": coc.signed_pdf_hash,
                "submitted_payload_hash": coc.submitted_payload_hash,
                "receipt_hash": coc.receipt_hash,
            }
            if coc is not None
            else None
        ),
        "receipt": (
            {
                "sucesso": rcpt.sucesso,
                "mensagem": rcpt.mensagem,  # protocol status text
                "protocolo": rcpt.protocolo,  # receipt number
                "data_recebimento": (
                    rcpt.data_recebimento.isoformat() if rcpt.data_recebimento else None
                ),
                "numero_processo": rcpt.numero_processo,
                "pdf_hash": rcpt.pdf_hash,
            }
            if rcpt is not None
            else None
        ),
    }


def _payload_to_result(payload: dict[str, object]) -> FilingResult:
    coc = payload.get("chain_of_custody")
    ids = payload.get("audit_entry_ids")
    error = payload.get("error")
    return FilingResult(
        success=bool(payload.get("success")),
        receipt=_receipt_from_payload(payload.get("receipt")),  # protocol metadata only
        signing_result=None,  # the signed PDF stays at the agent
        preflight=None,
        audit_entry_ids=list(ids) if isinstance(ids, list) else [],
        chain_of_custody=ChainOfCustody(**coc) if isinstance(coc, dict) else None,
        error=error if isinstance(error, str) else None,
    )


def _receipt_from_payload(data: object) -> FilingReceipt | None:
    """Rebuild the protocol receipt (metadata only) from the wire payload."""
    if not isinstance(data, dict):
        return None
    from datetime import datetime

    from juris.mni.operations.peticionamento import FilingReceipt

    dr = data.get("data_recebimento")
    return FilingReceipt(
        sucesso=bool(data.get("sucesso")),
        mensagem=str(data.get("mensagem", "")),
        protocolo=data.get("protocolo") if isinstance(data.get("protocolo"), str) else None,
        data_recebimento=datetime.fromisoformat(dr) if isinstance(dr, str) else None,
        numero_processo=(
            data.get("numero_processo") if isinstance(data.get("numero_processo"), str) else None
        ),
        pdf_hash=data.get("pdf_hash") if isinstance(data.get("pdf_hash"), str) else None,
    )


class FilingTransport(Protocol):
    def send(self, request: AgentRequest) -> AgentResponse: ...


class RemoteFilingService(FilingService):
    """Files by forwarding to the lawyer's agent over ``/ws/file`` (token stays remote)."""

    def __init__(self, transport: FilingTransport, *, tenant_id: str = "public") -> None:
        self._transport = transport
        self._tenant_id = tenant_id

    async def file(self, request: FilingRequest, *, pin: str | None = None) -> FilingResult:
        # cpf / senha / PIN are blanked — the agent resolves the lawyer's own.
        payload = {
            "numero_cnj": request.numero_cnj,
            "tribunal": request.tribunal,
            "tipo_documento": request.tipo_documento,
            "draft_markdown": request.draft_markdown,
            "tipo_peticao": request.tipo_peticao,
            "skip_preflight": request.skip_preflight,
            "dry_run": request.dry_run,
            "prazo_override": request.prazo_override,
        }
        agent_request = AgentRequest(
            request_id=uuid.uuid4().hex, tenant_id=self._tenant_id, operation="file", payload=payload
        )
        # The transport is a blocking (sync) WebSocket; run it off the event loop so
        # an async orchestrator isn't stalled while the agent files.
        response = await asyncio.to_thread(self._transport.send, agent_request)
        if response.request_id != agent_request.request_id:
            msg = "resposta de filing não correlaciona com o pedido"
            raise RuntimeError(msg)
        if not response.success:
            raise RuntimeError(response.error or "filing remoto falhou")
        return _payload_to_result(response.payload or {})


def build_filing_request(payload: dict[str, object], *, cpf: str, senha: str) -> FilingRequest:
    """Rebuild a FilingRequest at the agent, injecting the locally-resolved credentials."""
    return FilingRequest(
        numero_cnj=str(payload["numero_cnj"]),
        tribunal=str(payload["tribunal"]),
        tipo_documento=str(payload["tipo_documento"]),
        draft_markdown=str(payload["draft_markdown"]),
        tipo_peticao=str(payload["tipo_peticao"]),
        cpf=cpf,
        senha=senha,
        skip_preflight=bool(payload.get("skip_preflight", False)),
        dry_run=bool(payload.get("dry_run", False)),
        prazo_override=payload.get("prazo_override"),  # type: ignore[arg-type]
    )


async def handle_file_request(
    request: AgentRequest,
    service: FilingService,
    *,
    credentials_resolver: Callable[[], tuple[str, str, str]],
) -> AgentResponse:
    """Agent side: resolve credentials locally, run the pipeline, return the proof."""
    try:
        cpf, senha, pin = credentials_resolver()
        filing_request = build_filing_request(request.payload, cpf=cpf, senha=senha)
        result = await service.file(filing_request, pin=pin)
    except Exception as exc:  # noqa: BLE001 — typed error back to the orchestrator
        return AgentResponse(request_id=request.request_id, success=False, error=str(exc))
    return AgentResponse(request_id=request.request_id, success=True, payload=_custody_to_payload(result))
