"""Tests for the filing orchestrator."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from juris.mni.operations.peticionamento import FilingReceipt
from juris.persistence.audit import AuditLog
from juris.persistence.filing_receipt import FilingReceiptStore
from juris.signing.filing import (
    FilingOrchestrator,
    FilingRequest,
    GroundingEvidence,
    _count_citations,
)
from juris.signing.pades import CertStatus, SigningResult


def _verified_grounding(draft_markdown: str) -> GroundingEvidence:
    """Grounding evidence that passes the Task 3 gate for this exact draft.

    These tests exercise behavior downstream of the gate (render, preflight,
    sign, submit) — not the gate itself, so they need evidence that trivially
    passes it.
    """
    import hashlib

    return GroundingEvidence(status="verified", draft_sha256=hashlib.sha256(draft_markdown.encode("utf-8")).hexdigest())

# --- Fixtures ---


class _CaptureLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


def _make_mni_factory() -> MagicMock:
    def factory(tribunal_id: str, auth: object) -> object:
        return object()

    mock_client = MagicMock()
    return create_autospec(factory, return_value=mock_client)


@pytest.fixture()
def audit_log(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture()
def receipt_store(tmp_path: Path, audit_log: AuditLog) -> FilingReceiptStore:
    return FilingReceiptStore(tmp_path / "filings", audit_log)


@pytest.fixture()
def mock_cert_status() -> CertStatus:
    return CertStatus(
        valid=True,
        cn="ADVOGADO TESTE:12345678901",
        cpf="12345678901",
        valid_until=date(2027, 12, 31),
        pin_attempts_remaining=None,
    )


@pytest.fixture()
def mock_signing_result() -> SigningResult:
    return SigningResult(
        signed_pdf=b"%PDF-1.4 signed content",
        signer_name="ADVOGADO TESTE",
        signer_cpf="12345678901",
        timestamp=datetime.now(UTC),
        pdf_hash="abc123",
        signed_pdf_hash="def456",
        cert_valid_until=date(2027, 12, 31),
    )


@pytest.fixture()
def mock_signer(mock_cert_status: CertStatus, mock_signing_result: SigningResult) -> MagicMock:
    signer = MagicMock()
    signer.validate_cert.return_value = mock_cert_status
    signer.sign.return_value = mock_signing_result
    return signer


@pytest.fixture()
def mock_mni_receipt() -> FilingReceipt:
    return FilingReceipt(
        sucesso=True,
        mensagem="Petição protocolada com sucesso",
        protocolo="PROT-2026-001",
        data_recebimento=datetime.now(UTC),
        numero_processo="0001234-56.2024.8.13.0001",
        pdf_hash="def456",
    )


@pytest.fixture()
def mock_mni_client_factory(mock_mni_receipt: FilingReceipt) -> MagicMock:
    del mock_mni_receipt
    return _make_mni_factory()


@pytest.fixture()
def mock_mni_auth() -> MagicMock:
    return MagicMock(name="mni_auth")


@pytest.fixture()
def filing_request() -> FilingRequest:
    draft_markdown = "# Contestação\n\nTexto da contestação conforme art. 335 do CPC."
    return FilingRequest(
        numero_cnj="0001234-56.2024.8.13.0001",
        tribunal="tjmg",
        tipo_documento="contestacao",
        draft_markdown=draft_markdown,
        tipo_peticao="contestacao",
        cpf="12345678901",
        senha="senha123",
        grounding=_verified_grounding(draft_markdown),
    )


def _make_orchestrator(
    signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mni_factory: MagicMock,
    mni_auth: object,
) -> FilingOrchestrator:
    return FilingOrchestrator(
        signer=signer,
        audit=audit_log,
        receipt_store=receipt_store,
        mni_client_factory=mni_factory,
        mni_auth=mni_auth,
    )


# --- Tests ---


def test_dry_run_does_not_sign_or_submit(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """Dry-run renders and runs preflight but does NOT sign or file."""
    request = FilingRequest(
        numero_cnj=filing_request.numero_cnj,
        tribunal=filing_request.tribunal,
        tipo_documento=filing_request.tipo_documento,
        draft_markdown=filing_request.draft_markdown,
        tipo_peticao=filing_request.tipo_peticao,
        cpf=filing_request.cpf,
        senha=filing_request.senha,
        dry_run=True,
        grounding=filing_request.grounding,
    )
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=2, pdf_hash="aaa"
        )
        result = asyncio.run(orch.file(request))

    assert result.success is True
    assert result.receipt is None
    assert result.signing_result is None
    mock_signer.sign.assert_not_called()

    # Check audit events
    entries = audit_log.read_all()
    event_types = [e.event_type for e in entries]
    assert "filing.dryrun" in event_types
    assert "filing.submit" not in event_types
    assert "filing.sign" not in event_types


def test_dry_run_emits_dryrun_not_submit(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """Dry-run audit events are 'filing.dryrun', not 'filing.submit'."""
    request = FilingRequest(
        numero_cnj=filing_request.numero_cnj,
        tribunal=filing_request.tribunal,
        tipo_documento=filing_request.tipo_documento,
        draft_markdown=filing_request.draft_markdown,
        tipo_peticao=filing_request.tipo_peticao,
        cpf=filing_request.cpf,
        senha=filing_request.senha,
        dry_run=True,
        grounding=filing_request.grounding,
    )
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="bbb"
        )
        result = asyncio.run(orch.file(request))

    assert result.success is True
    entries = audit_log.read_all()
    event_types = {e.event_type for e in entries}
    assert "filing.dryrun" in event_types
    assert "filing.submit" not in event_types


def test_preflight_blocker_aborts_filing(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    """Filing aborts when preflight finds a blocker."""
    draft_markdown = "# Test\n\nSome content."
    request = FilingRequest(
        numero_cnj="0001234-56.2024.8.13.0001",
        tribunal="tjmg",
        tipo_documento="INVALID_TYPE",
        draft_markdown=draft_markdown,
        tipo_peticao="contestacao",
        cpf="12345678901",
        senha="senha123",
        grounding=_verified_grounding(draft_markdown),
    )
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="ccc"
        )
        result = asyncio.run(orch.file(request))

    assert result.success is False
    assert result.preflight is not None
    assert not result.preflight.passed
    assert "Preflight blocked" in (result.error or "")
    mock_signer.sign.assert_not_called()


def test_full_pipeline_success(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_receipt: FilingReceipt,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """Full pipeline: render → preflight → sign → file → receipt."""
    mock_factory = _make_mni_factory()

    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with (
        patch("juris.signing.filing.render_petition_pdf") as mock_render,
        patch("juris.signing.filing.entregar_manifestacao", create=True),
        patch("juris.mni.operations.peticionamento.entregar_manifestacao", mock_mni_receipt),
    ):
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test content", page_count=3, pdf_hash="render_hash"
        )
        # Patch the import inside file()
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            return_value=mock_mni_receipt,
        ):
            result = asyncio.run(orch.file(filing_request))

    assert result.success is True
    assert result.receipt is not None
    assert result.receipt.sucesso is True
    assert result.signing_result is not None
    assert result.chain_of_custody is not None
    assert result.chain_of_custody.pdf_hash == "render_hash"
    mock_factory.assert_called_once_with(filing_request.tribunal, mock_mni_auth)

    # Verify audit trail
    entries = audit_log.read_all()
    event_types = [e.event_type for e in entries]
    assert "filing.render" in event_types
    assert "filing.preflight" in event_types
    assert "filing.consent" in event_types
    assert "filing.sign" in event_types
    assert "filing.submit" in event_types
    assert "filing.receipt" in event_types


def test_chain_of_custody_hashes_present(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_receipt: FilingReceipt,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """Chain of custody has all 4 hashes."""
    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="pdf_h"
        )
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            return_value=mock_mni_receipt,
        ):
            result = asyncio.run(orch.file(filing_request))

    if result.success and result.chain_of_custody:
        chain = result.chain_of_custody
        assert chain.pdf_hash
        assert chain.signed_pdf_hash
        assert chain.submitted_payload_hash
        assert chain.receipt_hash


def test_consent_summary_in_audit(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_receipt: FilingReceipt,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """Consent audit entry contains rich context."""
    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=2, pdf_hash="hash"
        )
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            return_value=mock_mni_receipt,
        ):
            asyncio.run(orch.file(filing_request))

    entries = audit_log.read_all()
    consent_entries = [e for e in entries if e.event_type == "filing.consent"]
    assert len(consent_entries) == 1
    details = consent_entries[0].details
    assert "numero_cnj" in details
    assert "tribunal" in details
    assert "page_count" in details
    assert "cert_cn" in details


def test_skip_preflight(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_receipt: FilingReceipt,
    mock_mni_auth: MagicMock,
) -> None:
    """skip_preflight=True skips preflight checks."""
    draft_markdown = "# Test\n\nContent."
    request = FilingRequest(
        numero_cnj="0001234-56.2024.8.13.0001",
        tribunal="tjmg",
        tipo_documento="contestacao",
        draft_markdown=draft_markdown,
        tipo_peticao="contestacao",
        cpf="12345678901",
        senha="senha123",
        skip_preflight=True,
        grounding=_verified_grounding(draft_markdown),
    )
    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="hash"
        )
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            return_value=mock_mni_receipt,
        ):
            result = asyncio.run(orch.file(request))

    assert result.success is True
    mock_signer.validate_cert.assert_not_called()


def test_render_failure_returns_error(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
    monkeypatch,
) -> None:
    """Render failure returns error result."""
    import juris.signing.filing as filing_module

    capture = _CaptureLogger()
    monkeypatch.setattr(filing_module, "logger", capture)
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch(
        "juris.signing.filing.render_petition_pdf",
        side_effect=ValueError("Empty markdown /var/private/render token=abc pin=1234"),
    ):
        result = asyncio.run(orch.file(filing_request))

    assert result.success is False
    assert "Render failed" in (result.error or "")
    dumped = json.dumps({"error": result.error, "audit": [e.details for e in audit_log.read_all()]})
    assert "falha operacional" in dumped
    assert "/var/private/render" not in dumped
    assert "token=abc" not in dumped
    assert "pin=1234" not in dumped
    logged = json.dumps([event[1] for event in capture.events], ensure_ascii=False)
    assert "/var/private/render" not in logged
    assert "token=abc" not in logged
    assert "pin=1234" not in logged
    assert "exc_info" not in capture.events[0][1]


def test_signing_failure_returns_error(
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_cert_status: CertStatus,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
    monkeypatch,
) -> None:
    """Signing failure returns error result."""
    import juris.signing.filing as filing_module

    capture = _CaptureLogger()
    monkeypatch.setattr(filing_module, "logger", capture)
    signer = MagicMock()
    signer.validate_cert.return_value = mock_cert_status
    signer.sign.side_effect = RuntimeError("Token disconnected /var/private/a3 token=abc pin=1234")

    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="hash"
        )
        result = asyncio.run(orch.file(filing_request))

    assert result.success is False
    assert "Signing failed" in (result.error or "")
    dumped = json.dumps({"error": result.error, "audit": [e.details for e in audit_log.read_all()]})
    assert "falha operacional" in dumped
    assert "/var/private/a3" not in dumped
    assert "token=abc" not in dumped
    assert "pin=1234" not in dumped
    logged = json.dumps([event[1] for event in capture.events], ensure_ascii=False)
    assert "/var/private/a3" not in logged
    assert "token=abc" not in logged
    assert "pin=1234" not in logged
    assert "exc_info" not in capture.events[0][1]


def test_submit_failure_returns_delivery_uncertain(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
    monkeypatch,
) -> None:
    """MNI submit failures are reported as delivery_uncertain (not a plain retryable
    error) and never expose local paths or secrets in result/audit — the entrega may
    already have reached the tribunal, so success/failure is genuinely unknown."""
    import juris.signing.filing as filing_module

    capture = _CaptureLogger()
    monkeypatch.setattr(filing_module, "logger", capture)
    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="hash"
        )
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            side_effect=RuntimeError("SOAP /var/private/mni token=abc pin=1234"),
        ):
            result = asyncio.run(orch.file(filing_request))

    assert result.success is False
    assert result.error_code == "delivery_uncertain"
    assert "PODE ter sido protocolada" in (result.error or "")
    entries = audit_log.read_all()
    delivery_uncertain_entries = [e for e in entries if e.event_type == "filing.delivery_uncertain"]
    assert len(delivery_uncertain_entries) == 1
    assert delivery_uncertain_entries[0].details == {
        "error": (
            "Falha na entrega ao tribunal. ATENÇÃO: a petição PODE ter sido protocolada — "
            "confira o processo no tribunal antes de tentar novamente."
        ),
        "pending_receipt": True,
    }
    dumped = json.dumps({"error": result.error, "audit": [e.details for e in entries]})
    assert "confira o processo no tribunal" in dumped
    assert "/var/private/mni" not in dumped
    assert "token=abc" not in dumped
    assert "pin=1234" not in dumped
    assert "pending_path" not in dumped
    logged = json.dumps([event[1] for event in capture.events], ensure_ascii=False)
    assert "/var/private/mni" not in logged
    assert "token=abc" not in logged
    assert "pin=1234" not in logged
    assert "exc_info" not in capture.events[0][1]


def test_mni_rejection_returns_no_error_code(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """When the tribunal itself REJECTS the petition (receipt.sucesso=False, a
    definitive response — not an exception), error_code must stay None. Unlike
    delivery_uncertain, this is a known outcome: the UI must not show the
    'não reenvie sem verificar' notice for a plain rejection."""
    rejected_receipt = FilingReceipt(
        sucesso=False,
        mensagem="Documento fora do padrão exigido",
        protocolo=None,
        data_recebimento=None,
        numero_processo=filing_request.numero_cnj,
        pdf_hash="def456",
    )
    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="hash"
        )
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            return_value=rejected_receipt,
        ):
            result = asyncio.run(orch.file(filing_request))

    assert result.success is False
    assert result.error_code is None
    assert "MNI rejected" in (result.error or "")
    assert result.receipt is rejected_receipt


def test_audit_integrity_after_full_pipeline(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_receipt: FilingReceipt,
    mock_mni_auth: MagicMock,
    filing_request: FilingRequest,
) -> None:
    """Audit log has no corrupted entries after full pipeline."""
    mock_factory = _make_mni_factory()
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(
            pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="hash"
        )
        with patch(
            "juris.mni.operations.peticionamento.entregar_manifestacao",
            return_value=mock_mni_receipt,
        ):
            asyncio.run(orch.file(filing_request))

    corrupted = audit_log.verify_integrity()
    assert corrupted == []


def test_count_citations() -> None:
    """Citation counter detects legal references."""
    md = "Conforme art. 335 do CPC e Súmula 331 do TST, REsp 12345."
    count = _count_citations(md)
    assert count >= 2
