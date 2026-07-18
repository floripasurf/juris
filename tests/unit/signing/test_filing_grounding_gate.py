"""Tests for the grounding gate in FilingOrchestrator (Task 3).

Nothing reverified citation grounding before signing/filing. These tests pin
the contract: the gate runs as step 0 of ``FilingOrchestrator.file()``, before
render, on every path (dry-run included; ``skip_preflight`` does not bypass
it) — verified evidence with a matching draft hash passes; anything else
blocks with ``error_code`` unless the lawyer supplies an audited override.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from juris.persistence.audit import AuditLog
from juris.persistence.filing_receipt import FilingReceiptStore
from juris.signing.filing import FilingOrchestrator, FilingRequest, GroundingEvidence
from juris.signing.pades import CertStatus, SigningResult

DRAFT_MARKDOWN = "# Contestação\n\nTexto da contestação conforme art. 335 do CPC."


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture()
def audit_log(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture()
def receipt_store(tmp_path: Path, audit_log: AuditLog) -> FilingReceiptStore:
    return FilingReceiptStore(tmp_path / "filings", audit_log)


@pytest.fixture()
def mock_signer() -> MagicMock:
    signer = MagicMock()
    signer.validate_cert.return_value = CertStatus(
        valid=True,
        cn="ADVOGADO TESTE:12345678901",
        cpf="12345678901",
        valid_until=date(2027, 12, 31),
        pin_attempts_remaining=None,
    )
    signer.sign.return_value = SigningResult(
        signed_pdf=b"%PDF-1.4 signed content",
        signer_name="ADVOGADO TESTE",
        signer_cpf="12345678901",
        timestamp=datetime.now(UTC),
        pdf_hash="abc123",
        signed_pdf_hash="def456",
        cert_valid_until=date(2027, 12, 31),
    )
    return signer


@pytest.fixture()
def mock_mni_client_factory() -> MagicMock:
    def factory(tribunal_id: str, auth: object) -> object:
        return object()

    return create_autospec(factory, return_value=MagicMock())


@pytest.fixture()
def mock_mni_auth() -> MagicMock:
    return MagicMock(name="mni_auth")


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


def _base_request(**overrides: object) -> FilingRequest:
    fields: dict[str, object] = {
        "numero_cnj": "0001234-56.2024.8.13.0001",
        "tribunal": "tjmg",
        "tipo_documento": "contestacao",
        "draft_markdown": DRAFT_MARKDOWN,
        "tipo_peticao": "contestacao",
        "cpf": "12345678901",
        "senha": "senha123",
    }
    fields.update(overrides)
    return FilingRequest(**fields)  # type: ignore[arg-type]


# --- 1. verified + matching hash → pipeline continues (reaches render) ---


def test_verified_grounding_with_matching_hash_reaches_render(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    grounding = GroundingEvidence(status="verified", draft_sha256=_sha256(DRAFT_MARKDOWN))
    request = _base_request(grounding=grounding, dry_run=True)
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="aaa")
        result = asyncio.run(orch.file(request))

    mock_render.assert_called_once()
    assert result.success is True
    assert result.error_code is None
    event_types = {e.event_type for e in audit_log.read_all()}
    assert "filing.blocked_ungrounded" not in event_types


# --- 2. hash mismatch → grounding_required, nothing signed ---


def test_hash_mismatch_blocks_with_grounding_required(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    grounding = GroundingEvidence(status="verified", draft_sha256=_sha256("outra minuta qualquer"))
    request = _base_request(grounding=grounding)
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        result = asyncio.run(orch.file(request))

    assert result.success is False
    assert result.error_code == "grounding_required"
    mock_render.assert_not_called()
    mock_signer.sign.assert_not_called()
    event_types = [e.event_type for e in audit_log.read_all()]
    assert event_types == ["filing.blocked_ungrounded"]


# --- 3. revisao_humana_obrigatoria → distinct error_code ---


def test_revisao_humana_obrigatoria_blocks_with_specific_code(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    grounding = GroundingEvidence(
        status="verified",
        draft_sha256=_sha256(DRAFT_MARKDOWN),
        revisao_humana_obrigatoria=True,
    )
    request = _base_request(grounding=grounding)
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        result = asyncio.run(orch.file(request))

    assert result.success is False
    assert result.error_code == "revisao_humana_obrigatoria"
    mock_render.assert_not_called()


# --- 4. grounding=None (manifest antigo / documento externo) → grounding_required ---


def test_missing_grounding_blocks_as_grounding_required(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    request = _base_request(grounding=None)
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    result = asyncio.run(orch.file(request))

    assert result.success is False
    assert result.error_code == "grounding_required"


# --- 5. override: reason >= 20 chars continues + audits; short reason still blocks ---


def test_override_with_sufficient_reason_continues_and_audits(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    request = _base_request(
        grounding=None,
        dry_run=True,
        grounding_override=True,
        grounding_override_reason="Documento externo revisado manualmente pelo advogado responsável.",
    )
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    with patch("juris.signing.filing.render_petition_pdf") as mock_render:
        mock_render.return_value = MagicMock(pdf_bytes=b"%PDF-1.4 test", page_count=1, pdf_hash="aaa")
        result = asyncio.run(orch.file(request))

    mock_render.assert_called_once()
    assert result.success is True
    entries = audit_log.read_all()
    override_entries = [e for e in entries if e.event_type == "filing.grounding_override"]
    assert len(override_entries) == 1
    assert override_entries[0].actor == "lawyer"
    assert "revisado manualmente" in override_entries[0].details["reason"]


def test_override_with_short_reason_still_blocks(
    mock_signer: MagicMock,
    audit_log: AuditLog,
    receipt_store: FilingReceiptStore,
    mock_mni_client_factory: MagicMock,
    mock_mni_auth: MagicMock,
) -> None:
    request = _base_request(
        grounding=None,
        grounding_override=True,
        grounding_override_reason="curto",
    )
    orch = _make_orchestrator(mock_signer, audit_log, receipt_store, mock_mni_client_factory, mock_mni_auth)

    result = asyncio.run(orch.file(request))

    assert result.success is False
    assert result.error_code == "grounding_required"
    entries = audit_log.read_all()
    assert not [e for e in entries if e.event_type == "filing.grounding_override"]
