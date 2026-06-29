"""Tests for remote filing — split-trust client + agent handler (ADR-0015, P4)."""

from __future__ import annotations

import asyncio

import pytest

from juris.api.ws_schemas import AgentRequest, AgentResponse
from juris.signing.filing import ChainOfCustody, FilingRequest, FilingResult
from juris.signing.filing_service import FilingService, RemoteFilingService, handle_file_request


def _req(**kw: object) -> FilingRequest:
    base: dict[str, object] = {
        "numero_cnj": "5082351-40.2017.8.13.0024",
        "tribunal": "tjmg",
        "tipo_documento": "manifestacao",
        "draft_markdown": "# Peça",
        "tipo_peticao": "contestacao",
        "cpf": "CLOUD-cpf",
        "senha": "CLOUD-senha",
        "skip_preflight": False,
        "dry_run": False,
        "prazo_override": None,
    }
    base.update(kw)
    return FilingRequest(**base)  # type: ignore[arg-type]


def _custody() -> ChainOfCustody:
    return ChainOfCustody(pdf_hash="p", signed_pdf_hash="s", submitted_payload_hash="sub", receipt_hash="r")


class _FakeFiling(FilingService):
    def __init__(self) -> None:
        self.seen_cpf: str | None = None
        self.seen_pin: str | None = None

    async def file(self, request: FilingRequest, *, pin: str | None = None) -> FilingResult:
        self.seen_cpf = request.cpf
        self.seen_pin = pin
        return FilingResult(
            success=True, receipt=None, signing_result=None, preflight=None,
            audit_entry_ids=["a1"], chain_of_custody=_custody(),
        )


def test_remote_filing_blanks_credentials_and_round_trips_proof() -> None:
    on_wire: list[str] = []

    class _Transport:
        def send(self, agent_request: AgentRequest) -> AgentResponse:
            on_wire.append(agent_request.model_dump_json())
            return AgentResponse(
                request_id=agent_request.request_id,
                success=True,
                payload={
                    "success": True,
                    "audit_entry_ids": ["a1"],
                    "chain_of_custody": {
                        "pdf_hash": "p", "signed_pdf_hash": "s",
                        "submitted_payload_hash": "sub", "receipt_hash": "r",
                    },
                },
            )

    service = RemoteFilingService(_Transport(), tenant_id="escritorio-x")
    result = asyncio.run(service.file(_req()))

    assert result.success
    assert result.chain_of_custody is not None
    assert result.chain_of_custody.signed_pdf_hash == "s"  # proof crossed
    assert "CLOUD-cpf" not in on_wire[0]  # no credential crossed
    assert "CLOUD-senha" not in on_wire[0]
    assert "escritorio-x" in on_wire[0]  # tenant tagged


@pytest.mark.asyncio
async def test_handle_file_request_resolves_credentials_locally() -> None:
    fake = _FakeFiling()
    req = AgentRequest(
        request_id="f1",
        operation="file",
        payload={
            "numero_cnj": "123", "tribunal": "tjmg", "tipo_documento": "manifestacao",
            "draft_markdown": "# P", "tipo_peticao": "contestacao",
        },
    )

    resp = await handle_file_request(
        req, fake, credentials_resolver=lambda: ("agent-cpf", "agent-senha", "agent-pin")
    )

    assert resp.success
    assert resp.payload["chain_of_custody"]["signed_pdf_hash"] == "s"
    assert fake.seen_cpf == "agent-cpf"  # the agent injected ITS credentials
    assert fake.seen_pin == "agent-pin"


def test_filing_factory_inprocess_by_default(monkeypatch) -> None:
    from juris.signing.filing_service import InProcessFilingService, get_filing_service

    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    assert isinstance(get_filing_service(), InProcessFilingService)


def test_filing_factory_remote_when_configured(monkeypatch) -> None:
    from juris.signing.filing_service import get_filing_service

    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    assert isinstance(get_filing_service(), RemoteFilingService)


def test_remote_filing_carries_protocol_metadata_not_artifacts() -> None:
    from datetime import UTC, datetime

    from juris.mni.operations.peticionamento import FilingReceipt
    from juris.signing.filing_service import _custody_to_payload, _payload_to_result

    receipt = FilingReceipt(
        sucesso=True, mensagem="Recebido", protocolo="PROTO-2026-123",
        data_recebimento=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        numero_processo="5082351-40.2017.8.13.0024", pdf_hash="ph",
    )
    result = FilingResult(
        success=True, receipt=receipt, signing_result=None, preflight=None,
        audit_entry_ids=["a1"], chain_of_custody=_custody(),
    )

    payload = _custody_to_payload(result)
    assert payload["receipt"]["protocolo"] == "PROTO-2026-123"  # receipt number
    assert payload["receipt"]["numero_processo"] == "5082351-40.2017.8.13.0024"
    assert payload["receipt"]["mensagem"] == "Recebido"  # status text

    rebuilt = _payload_to_result(payload)
    assert rebuilt.receipt is not None
    assert rebuilt.receipt.protocolo == "PROTO-2026-123"
    assert rebuilt.receipt.data_recebimento.year == 2026
    assert rebuilt.signing_result is None  # the signed PDF never crosses
