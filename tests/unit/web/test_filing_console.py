"""Tests for web filing status and serialization helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from juris.mni.operations.peticionamento import FilingReceipt
from juris.signing.filing import ChainOfCustody, FilingResult
from juris.signing.pades import SigningResult
from juris.web.filing_console import filing_status, serialize_filing_result


def test_filing_status_lists_pending_and_receipts(tmp_path) -> None:
    cnj_dir = tmp_path / "0001234_56_2026_8_13_0001"
    pending = cnj_dir / "20260630_120000_pending"
    done = cnj_dir / "20260630_121000_PROT_1"
    pending.mkdir(parents=True)
    done.mkdir()
    (pending / "hashes.json").write_text(json.dumps({"signed_pdf_hash": "signed-pending"}), encoding="utf-8")
    (done / "receipt.json").write_text(
        json.dumps({"protocolo": "PROT-1", "mensagem": "ok", "numero_processo": "0001234"}),
        encoding="utf-8",
    )
    (done / "metadata.json").write_text(
        json.dumps({"tribunal": "tjmg", "tipo_documento": "manifestacao", "filed_at": "2026-06-30T12:10:00"}),
        encoding="utf-8",
    )
    (done / "hashes.json").write_text(
        json.dumps({"pdf_hash": "pdf", "signed_pdf_hash": "signed", "receipt_hash": "receipt"}),
        encoding="utf-8",
    )

    status = filing_status(tmp_path)

    assert status["pending"][0]["hashes"]["signed_pdf_hash"] == "signed-pending"
    assert status["recent_receipts"][0]["protocolo"] == "PROT-1"
    assert status["recent_receipts"][0]["hashes"]["receipt_hash"] == "receipt"


def test_serialize_filing_result_does_not_expose_pdf_bytes() -> None:
    result = FilingResult(
        success=True,
        receipt=FilingReceipt(sucesso=True, mensagem="ok", protocolo="P1", numero_processo="0001234"),
        signing_result=SigningResult(
            signed_pdf=b"%PDF sensitive",
            signer_name="Dra. Ana",
            signer_cpf="12345678900",
            timestamp=datetime(2026, 6, 30, 12, tzinfo=UTC),
            pdf_hash="pdf",
            signed_pdf_hash="signed",
            cert_valid_until=datetime(2030, 1, 1, tzinfo=UTC).date(),
        ),
        preflight=None,
        audit_entry_ids=["a1"],
        chain_of_custody=ChainOfCustody(
            pdf_hash="pdf",
            signed_pdf_hash="signed",
            submitted_payload_hash="payload",
            receipt_hash="receipt",
        ),
    )

    payload = serialize_filing_result(result)

    assert payload["receipt"]["protocolo"] == "P1"
    assert payload["chain_of_custody"]["receipt_hash"] == "receipt"
    dumped = json.dumps(payload)
    assert "%PDF sensitive" not in dumped
    assert '"signed_pdf":' not in dumped
