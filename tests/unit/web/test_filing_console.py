"""Tests for web filing status and serialization helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from juris.mni.operations.peticionamento import FilingReceipt
from juris.signing.filing import ChainOfCustody, FilingResult
from juris.signing.pades import SigningResult
from juris.web.filing_console import (
    archive_pending,
    filing_artifacts,
    filing_status,
    pending_recovery,
    read_filing_artifact,
    serialize_filing_result,
)


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
    assert status["pending"][0]["pending_key"] == "0001234_56_2026_8_13_0001/20260630_120000_pending"
    assert status["pending"][0]["signed_pdf_size"] is None
    assert status["recent_receipts"][0]["protocolo"] == "PROT-1"
    assert status["recent_receipts"][0]["hashes"]["receipt_hash"] == "receipt"


def test_pending_recovery_and_archive_preserve_files(tmp_path) -> None:
    cnj_dir = tmp_path / "0001234_56_2026_8_13_0001"
    pending = cnj_dir / "20260630_120000_pending"
    pending.mkdir(parents=True)
    (pending / "signed.pdf").write_bytes(b"%PDF signed")
    (pending / "hashes.json").write_text(json.dumps({"signed_pdf_hash": "signed"}), encoding="utf-8")
    key = "0001234_56_2026_8_13_0001/20260630_120000_pending"

    recovery = pending_recovery(tmp_path, key)
    archived = archive_pending(tmp_path, key, reason="protocolo conferido no portal")

    assert recovery["pending_key"] == key
    assert recovery["safe_to_retry"] is False
    assert "signed.pdf" not in json.dumps(recovery)
    archived_path = tmp_path / "0001234_56_2026_8_13_0001" / "20260630_120000_manual_resolution"
    assert archived["archived"] is True
    assert archived_path.exists()
    assert (archived_path / "signed.pdf").read_bytes() == b"%PDF signed"
    recovery_record = json.loads((archived_path / "recovery.json").read_text(encoding="utf-8"))
    assert recovery_record["reason"] == "protocolo conferido no portal"
    assert filing_status(tmp_path)["pending"] == []


def test_archive_pending_requires_reason(tmp_path) -> None:
    cnj_dir = tmp_path / "0001234"
    (cnj_dir / "20260630_pending").mkdir(parents=True)

    try:
        archive_pending(tmp_path, "0001234/20260630_pending", reason=" ")
    except ValueError as exc:
        assert "justificativa" in str(exc)
    else:
        raise AssertionError("archive sem justificativa deveria falhar")


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


def test_filing_artifacts_lists_primary_drafts(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    (case_dir / "draft.md").write_text("# Minuta", encoding="utf-8")
    (case_dir / "other.md").write_text("não listar", encoding="utf-8")
    (case_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "finished_at": "2026-06-30T12:00:00",
                "output_mode": "minuta-sugerida",
                "request": {"numero_cnj": "0001234", "tribunal": "tjmg", "tipo_peticao": "contestacao"},
                "draft": {"grounding_status": "verified"},
                "artifacts": [
                    {"name": "draft.md", "sha256": "draft-hash"},
                    {"name": "other.md", "sha256": "other-hash"},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = filing_artifacts(tmp_path)

    assert len(payload["artifacts"]) == 1
    artifact = payload["artifacts"][0]
    assert artifact["artifact_name"] == "draft.md"
    assert artifact["numero_cnj"] == "0001234"
    assert artifact["grounding_status"] == "verified"


def test_read_filing_artifact_is_confined_to_root(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    (case_dir / "draft.md").write_text("# Minuta", encoding="utf-8")

    payload = read_filing_artifact(tmp_path, output_dir="CASE-1", artifact_name="draft.md")

    assert payload["content"] == "# Minuta"

    try:
        read_filing_artifact(tmp_path, output_dir="../", artifact_name="draft.md")
    except ValueError as exc:
        assert "fora do diretório" in str(exc)
    else:
        raise AssertionError("path traversal deveria falhar")

    try:
        read_filing_artifact(tmp_path, output_dir="CASE-1", artifact_name="run-manifest.json")
    except ValueError as exc:
        assert "não permitido" in str(exc)
    else:
        raise AssertionError("artefato não primário deveria falhar")
