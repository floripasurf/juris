"""Tests for remote filing — split-trust client + agent handler (ADR-0015, P4)."""

from __future__ import annotations

import asyncio

import pytest

from juris.api.ws_schemas import AgentRequest, AgentResponse
from juris.signing.filing import ChainOfCustody, FilingRequest, FilingResult, GroundingEvidence
from juris.signing.filing_service import FilingService, RemoteFilingService, handle_file_request


class _CaptureLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


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
        self.seen_draft_markdown: str | None = None

    async def file(self, request: FilingRequest, *, pin: str | None = None) -> FilingResult:
        self.seen_cpf = request.cpf
        self.seen_pin = pin
        self.seen_draft_markdown = request.draft_markdown
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


def test_remote_filing_keeps_reid_map_and_raw_pii_off_the_wire() -> None:
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
    result = asyncio.run(
        service.file(_req(draft_markdown="# Peça\nAutor: [NOME_1]\nCPF: [CPF_1]"))
    )

    assert result.success
    assert "[NOME_1]" in on_wire[0]
    assert "[CPF_1]" in on_wire[0]
    assert "João da Silva" not in on_wire[0]
    assert "123.456.789-09" not in on_wire[0]
    assert "reid" not in on_wire[0].lower()


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


@pytest.mark.asyncio
async def test_handle_file_request_reidentifies_draft_locally(monkeypatch, tmp_path) -> None:
    from juris.api.reid_store import save_reid_map

    monkeypatch.setenv("JURIS_AGENT_DEID_READS", "1")
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    numero_cnj = "5082351-40.2017.8.13.0024"
    save_reid_map(
        "escritorio-x",
        numero_cnj,
        {"[NOME_1]": "João da Silva", "[CPF_1]": "123.456.789-09"},
    )
    fake = _FakeFiling()
    req = AgentRequest(
        request_id="f-reid",
        tenant_id="escritorio-x",
        operation="file",
        payload={
            "numero_cnj": numero_cnj,
            "tribunal": "tjmg",
            "tipo_documento": "manifestacao",
            "draft_markdown": "# Peça\nAutor: [NOME_1]\nCPF: [CPF_1]",
            "tipo_peticao": "contestacao",
        },
    )

    resp = await handle_file_request(
        req, fake, credentials_resolver=lambda: ("agent-cpf", "agent-senha", "agent-pin")
    )

    assert resp.success
    assert fake.seen_draft_markdown is not None
    assert "João da Silva" in fake.seen_draft_markdown
    assert "123.456.789-09" in fake.seen_draft_markdown
    assert "[NOME_1]" not in fake.seen_draft_markdown
    assert "[CPF_1]" not in fake.seen_draft_markdown


def test_reidentify_agent_draft_downgrades_grounding_to_unknown_and_warns(monkeypatch, tmp_path) -> None:
    """Task 3 follow-up: the grounding evidence's draft_sha256 is computed
    SaaS-side over the de-identified markdown; reidentification here rewrites
    the draft AFTER that hash was taken, so it can never match again. Letting
    that surface only as an incidental hash-mismatch block hides *why* — this
    downgrade makes the degradation explicit and observable instead."""
    import juris.signing.filing_service as filing_service_module
    from juris.api.reid_store import save_reid_map

    monkeypatch.setenv("JURIS_AGENT_DEID_READS", "1")
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    numero_cnj = "5082351-40.2017.8.13.0024"
    save_reid_map("escritorio-x", numero_cnj, {"[NOME_1]": "João da Silva"})
    capture = _CaptureLogger()
    monkeypatch.setattr(filing_service_module, "logger", capture)

    payload = {
        "numero_cnj": numero_cnj,
        "draft_markdown": "# Peça\nAutor: [NOME_1]",
        "grounding": {"status": "verified", "draft_sha256": "a" * 64, "revisao_humana_obrigatoria": False},
    }

    restored = filing_service_module._reidentify_agent_draft(payload, tenant_id="escritorio-x")

    assert "João da Silva" in restored["draft_markdown"]
    assert restored["grounding"]["status"] == "unknown"
    assert restored["grounding"]["draft_sha256"] == "a" * 64  # untouched — only the status is downgraded
    events = [e for e in capture.events if e[0] == "grounding_evidence_invalidated_by_deid_reads"]
    assert len(events) == 1
    assert events[0][1]["tenant_id"] == "escritorio-x"
    assert events[0][1]["numero_cnj"] == numero_cnj


def test_reidentify_agent_draft_skips_downgrade_without_reidentification(monkeypatch, tmp_path) -> None:
    """No mapping found (or deid-reads off) → the draft is never rewritten, so
    the evidence is still valid for it — no warning, no downgrade."""
    import juris.signing.filing_service as filing_service_module

    monkeypatch.setenv("JURIS_AGENT_DEID_READS", "1")
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    capture = _CaptureLogger()
    monkeypatch.setattr(filing_service_module, "logger", capture)

    payload = {
        "numero_cnj": "5082351-40.2017.8.13.0024",  # no reid map saved for this cnj
        "draft_markdown": "# Peça",
        "grounding": {"status": "verified", "draft_sha256": "a" * 64, "revisao_humana_obrigatoria": False},
    }

    restored = filing_service_module._reidentify_agent_draft(payload, tenant_id="escritorio-x")

    assert restored["grounding"]["status"] == "verified"  # unchanged
    assert capture.events == []


@pytest.mark.asyncio
async def test_handle_file_request_blocks_grounding_when_deid_reads_reidentifies(monkeypatch, tmp_path) -> None:
    """End-to-end: deid-reads on + a verified evidence for the (pre-reid) draft
    still ends up grounding_required through the REAL orchestrator gate —
    nothing gets rendered, signed, or filed."""
    import hashlib

    from juris.api.reid_store import save_reid_map
    from juris.signing.filing_service import InProcessFilingService

    monkeypatch.setenv("JURIS_AGENT_DEID_READS", "1")
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    numero_cnj = "5082351-40.2017.8.13.0024"
    save_reid_map("escritorio-x", numero_cnj, {"[NOME_1]": "João da Silva"})
    draft_markdown = "# Peça\nAutor: [NOME_1]"
    draft_sha256 = hashlib.sha256(draft_markdown.encode("utf-8")).hexdigest()

    req = AgentRequest(
        request_id="f-deid-grounding",
        tenant_id="escritorio-x",
        operation="file",
        payload={
            "numero_cnj": numero_cnj,
            "tribunal": "tjmg",
            "tipo_documento": "manifestacao",
            "draft_markdown": draft_markdown,
            "tipo_peticao": "contestacao",
            # dry_run+skip_preflight so run_filing() uses its mock signer path —
            # the gate must block regardless, and this keeps the test from
            # needing a real A3 token to reach it.
            "dry_run": True,
            "skip_preflight": True,
            "grounding": {"status": "verified", "draft_sha256": draft_sha256, "revisao_humana_obrigatoria": False},
        },
    )
    service = InProcessFilingService(storage_root=tmp_path / "juris-storage")

    resp = await handle_file_request(
        req, service, credentials_resolver=lambda: ("agent-cpf", "agent-senha", "agent-pin")
    )

    assert resp.success is True  # the wire call itself succeeded
    assert resp.payload["success"] is False  # but the FilingResult inside is blocked
    assert resp.payload["error_code"] == "grounding_required"


@pytest.mark.asyncio
async def test_handle_file_request_does_not_leak_internal_error() -> None:
    class _BoomFiling(FilingService):
        async def file(self, request, *, pin=None):  # noqa: ANN001, ANN201
            raise RuntimeError("protocolo /var/private/a3 token=abc pin=1234")

    req = AgentRequest(
        request_id="f2",
        operation="file",
        payload={
            "numero_cnj": "123", "tribunal": "tjmg", "tipo_documento": "manifestacao",
            "draft_markdown": "# P", "tipo_peticao": "contestacao",
        },
    )

    resp = await handle_file_request(
        req, _BoomFiling(), credentials_resolver=lambda: ("agent-cpf", "agent-senha", "agent-pin")
    )

    assert resp.success is False
    assert "Falha ao protocolar" in (resp.error or "")
    assert "token=abc" not in (resp.error or "")
    assert "pin=1234" not in (resp.error or "")
    assert "/var/private/a3" not in (resp.error or "")


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


def test_filing_factory_uses_relay_transport_for_relay_binding(tmp_path, monkeypatch) -> None:
    import json

    from juris.api.agent_config import _load_agent_bindings
    from juris.mni.remote import RelayAgentTransport
    from juris.signing.filing_service import get_filing_service

    agents = tmp_path / "agents.json"
    agents.write_text(
        json.dumps(
            {
                "trial-a": {
                    "url": "wss://app.example/ws/agent-relay",
                    "token": "tok-a",
                    "transport": "relay",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))
    _load_agent_bindings.cache_clear()

    service = get_filing_service("trial-a")
    assert isinstance(service._transport, RelayAgentTransport)


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


def test_remote_filing_round_trips_delivery_uncertain_error_code() -> None:
    """The agent may hit an indeterminate MNI delivery too — error_code must cross
    the wire so the console can withhold the immediate-resend option there as well."""
    from juris.signing.filing_service import _custody_to_payload, _payload_to_result

    result = FilingResult(
        success=False, receipt=None, signing_result=None, preflight=None,
        audit_entry_ids=["a1"],
        error="Falha na entrega ao tribunal. ATENÇÃO: a petição PODE ter sido protocolada — "
        "confira o processo no tribunal antes de tentar novamente.",
        error_code="delivery_uncertain",
    )

    payload = _custody_to_payload(result)
    assert payload["error_code"] == "delivery_uncertain"

    rebuilt = _payload_to_result(payload)
    assert rebuilt.error_code == "delivery_uncertain"
    assert rebuilt.success is False


def test_remote_filing_forwards_grounding_evidence_over_the_wire() -> None:
    """The grounding gate runs at the agent (where signing happens) — the SaaS-side
    evidence resolved from the manifest must cross the wire or every remote filing
    would be blocked with grounding_required regardless of local verification."""
    on_wire: list[str] = []

    class _Transport:
        def send(self, agent_request: AgentRequest) -> AgentResponse:
            on_wire.append(agent_request.model_dump_json())
            return AgentResponse(request_id=agent_request.request_id, success=True, payload={"success": True})

    service = RemoteFilingService(_Transport())
    grounding = GroundingEvidence(status="verified", draft_sha256="a" * 64, revisao_humana_obrigatoria=False)
    asyncio.run(
        service.file(
            _req(
                grounding=grounding,
                grounding_override=True,
                grounding_override_reason="Justificativa do advogado com mais de vinte caracteres.",
            )
        )
    )

    payload = AgentRequest.model_validate_json(on_wire[0]).payload
    assert payload["grounding"] == {
        "status": "verified",
        "draft_sha256": "a" * 64,
        "revisao_humana_obrigatoria": False,
        "numero_cnj": "",
        "tribunal": "",
        "tipo_peticao": "",
        "output_mode": "",
    }
    assert payload["grounding_override"] is True
    assert payload["grounding_override_reason"] == "Justificativa do advogado com mais de vinte caracteres."


def test_remote_filing_forwards_processo_binding_and_output_mode_over_the_wire() -> None:
    """Fix A: numero_cnj/tribunal/output_mode must cross the wire too — the
    agent-side gate binds evidence to the processo it was verified for and to
    a protocolable output_mode, same as the co-located gate."""
    on_wire: list[str] = []

    class _Transport:
        def send(self, agent_request: AgentRequest) -> AgentResponse:
            on_wire.append(agent_request.model_dump_json())
            return AgentResponse(request_id=agent_request.request_id, success=True, payload={"success": True})

    service = RemoteFilingService(_Transport())
    grounding = GroundingEvidence(
        status="verified",
        draft_sha256="a" * 64,
        numero_cnj="0001234-56.2024.8.13.0001",
        tribunal="tjmg",
        tipo_peticao="contestacao",
        output_mode="minuta-sugerida",
    )
    asyncio.run(service.file(_req(grounding=grounding)))

    payload = AgentRequest.model_validate_json(on_wire[0]).payload
    assert payload["grounding"]["numero_cnj"] == "0001234-56.2024.8.13.0001"
    assert payload["grounding"]["tribunal"] == "tjmg"
    assert payload["grounding"]["tipo_peticao"] == "contestacao"
    assert payload["grounding"]["output_mode"] == "minuta-sugerida"


def test_remote_filing_forwards_none_grounding_as_null() -> None:
    on_wire: list[str] = []

    class _Transport:
        def send(self, agent_request: AgentRequest) -> AgentResponse:
            on_wire.append(agent_request.model_dump_json())
            return AgentResponse(request_id=agent_request.request_id, success=True, payload={"success": True})

    service = RemoteFilingService(_Transport())
    asyncio.run(service.file(_req(grounding=None)))

    payload = AgentRequest.model_validate_json(on_wire[0]).payload
    assert payload["grounding"] is None
    assert payload["grounding_override"] is False


def test_build_filing_request_reconstructs_grounding_evidence() -> None:
    from juris.signing.filing_service import build_filing_request

    payload = {
        "numero_cnj": "123",
        "tribunal": "tjmg",
        "tipo_documento": "manifestacao",
        "draft_markdown": "# P",
        "tipo_peticao": "contestacao",
        "grounding": {"status": "verified", "draft_sha256": "b" * 64, "revisao_humana_obrigatoria": True},
        "grounding_override": True,
        "grounding_override_reason": "Justificativa registrada pelo advogado no agente.",
    }

    request = build_filing_request(payload, cpf="cpf", senha="senha")

    assert request.grounding == GroundingEvidence(
        status="verified", draft_sha256="b" * 64, revisao_humana_obrigatoria=True
    )
    assert request.grounding_override is True
    assert request.grounding_override_reason == "Justificativa registrada pelo advogado no agente."


def test_build_filing_request_reconstructs_processo_binding_and_output_mode() -> None:
    """Fix A round-trip: numero_cnj/tribunal/tipo_peticao/output_mode must survive
    serialization to the agent so its gate can bind evidence to the processo."""
    from juris.signing.filing_service import build_filing_request

    payload = {
        "numero_cnj": "123",
        "tribunal": "tjmg",
        "tipo_documento": "manifestacao",
        "draft_markdown": "# P",
        "tipo_peticao": "contestacao",
        "grounding": {
            "status": "verified",
            "draft_sha256": "b" * 64,
            "revisao_humana_obrigatoria": False,
            "numero_cnj": "0001234-56.2024.8.13.0001",
            "tribunal": "tjmg",
            "tipo_peticao": "contestacao",
            "output_mode": "minuta-sugerida",
        },
    }

    request = build_filing_request(payload, cpf="cpf", senha="senha")

    assert request.grounding == GroundingEvidence(
        status="verified",
        draft_sha256="b" * 64,
        numero_cnj="0001234-56.2024.8.13.0001",
        tribunal="tjmg",
        tipo_peticao="contestacao",
        output_mode="minuta-sugerida",
    )


def test_build_filing_request_defaults_grounding_to_none_when_absent() -> None:
    """Backward compatible with a relay/agent that hasn't been upgraded yet — absent
    keys must not crash, and default to the safe (blocked-unless-overridden) state."""
    from juris.signing.filing_service import build_filing_request

    payload = {
        "numero_cnj": "123",
        "tribunal": "tjmg",
        "tipo_documento": "manifestacao",
        "draft_markdown": "# P",
        "tipo_peticao": "contestacao",
    }

    request = build_filing_request(payload, cpf="cpf", senha="senha")

    assert request.grounding is None
    assert request.grounding_override is False
    assert request.grounding_override_reason == ""


def test_remote_filing_runs_blocking_transport_off_the_event_loop() -> None:
    import threading

    main_thread = threading.get_ident()
    captured: dict[str, int] = {}

    class _ThreadCheckTransport:
        def send(self, agent_request: AgentRequest) -> AgentResponse:
            captured["thread"] = threading.get_ident()
            return AgentResponse(request_id=agent_request.request_id, success=True, payload={"success": True})

    asyncio.run(RemoteFilingService(_ThreadCheckTransport()).file(_req()))
    assert captured["thread"] != main_thread  # the sync transport ran in a worker thread
