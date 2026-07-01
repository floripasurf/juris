"""Tests for web filing status and serialization helpers."""

from __future__ import annotations

import hashlib
import json
import stat
from datetime import UTC, datetime

from juris.mni.operations.peticionamento import FilingReceipt
from juris.signing.filing import ChainOfCustody, FilingResult
from juris.signing.pades import SigningResult
from juris.web.filing_console import (
    archive_pending,
    default_filing_root,
    filing_artifacts,
    filing_status,
    pending_recovery,
    read_filing_artifact,
    serialize_filing_result,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_default_filing_root_honors_juris_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    monkeypatch.delenv("JURIS_FILING_ROOT", raising=False)

    assert default_filing_root() == tmp_path / "filings"


def test_default_filing_root_prefers_explicit_override(tmp_path, monkeypatch) -> None:
    override = tmp_path / "custom-filings"
    monkeypatch.setenv("JURIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JURIS_FILING_ROOT", str(override))

    assert default_filing_root() == override


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
    assert status["recent_receipts"][0]["receipt_key"] == "0001234_56_2026_8_13_0001/20260630_121000_PROT_1"
    assert status["recent_receipts"][0]["hashes"]["receipt_hash"] == "receipt"
    dumped = json.dumps(status)
    assert str(tmp_path) not in dumped
    assert "filing_root" not in status
    assert "path" not in status["pending"][0]
    assert "path" not in status["recent_receipts"][0]


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
    assert str(tmp_path) not in json.dumps(recovery)
    archived_path = tmp_path / "0001234_56_2026_8_13_0001" / "20260630_120000_manual_resolution"
    assert archived["archived"] is True
    assert archived["archived_key"] == "0001234_56_2026_8_13_0001/20260630_120000_manual_resolution"
    assert str(tmp_path) not in json.dumps(archived)
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
    draft = "# Minuta"
    (case_dir / "draft.md").write_text(draft, encoding="utf-8")
    (case_dir / "other.md").write_text("não listar", encoding="utf-8")
    (case_dir / "run-manifest.json").write_text(
        json.dumps(
            {
                "finished_at": "2026-06-30T12:00:00",
                "output_mode": "minuta-sugerida",
                "request": {"numero_cnj": "0001234", "tribunal": "tjmg", "tipo_peticao": "contestacao"},
                "draft": {"grounding_status": "verified"},
                "artifacts": [
                    {"name": "draft.md", "sha256": _sha256_text(draft)},
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
    assert artifact["sha256_verified"] is True
    assert artifact["output_dir"] == "CASE-1"
    assert str(tmp_path) not in json.dumps(payload)


def test_filing_artifacts_skips_hash_mismatch(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    (case_dir / "draft.md").write_text("# Minuta adulterada", encoding="utf-8")
    (case_dir / "run-manifest.json").write_text(
        json.dumps({"artifacts": [{"name": "draft.md", "sha256": "0" * 64}]}),
        encoding="utf-8",
    )

    assert filing_artifacts(tmp_path)["artifacts"] == []


def test_read_filing_artifact_is_confined_to_root(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    content = "# Minuta"
    (case_dir / "draft.md").write_text(content, encoding="utf-8")
    (case_dir / "run-manifest.json").write_text(
        json.dumps({"artifacts": [{"name": "draft.md", "sha256": _sha256_text(content)}]}),
        encoding="utf-8",
    )

    payload = read_filing_artifact(tmp_path, output_dir="CASE-1", artifact_name="draft.md")

    assert payload["content"] == "# Minuta"
    assert payload["output_dir"] == "CASE-1"
    assert payload["sha256"] == _sha256_text(content)
    assert payload["sha256_verified"] is True
    assert str(tmp_path) not in json.dumps(payload)

    try:
        read_filing_artifact(tmp_path, output_dir="../", artifact_name="draft.md")
    except ValueError as exc:
        assert "fora do diretório" in str(exc)
    else:
        raise AssertionError("path traversal deveria falhar")

    try:
        read_filing_artifact(tmp_path, output_dir="CASE-1", artifact_name="../draft.md")
    except ValueError as exc:
        assert "não permitido" in str(exc)
    else:
        raise AssertionError("path traversal no nome do artefato deveria falhar")

    try:
        read_filing_artifact(tmp_path, output_dir="CASE-1", artifact_name="run-manifest.json")
    except ValueError as exc:
        assert "não permitido" in str(exc)
    else:
        raise AssertionError("artefato não primário deveria falhar")


def test_read_filing_artifact_rejects_symlink_escape(tmp_path) -> None:
    case_dir = tmp_path / "CASE-1"
    case_dir.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("# Fora", encoding="utf-8")
    try:
        (case_dir / "draft.md").symlink_to(outside)
        (case_dir / "run-manifest.json").write_text(
            json.dumps({"artifacts": [{"name": "draft.md", "sha256": _sha256_text("# Fora")}]}),
            encoding="utf-8",
        )

        try:
            read_filing_artifact(tmp_path, output_dir="CASE-1", artifact_name="draft.md")
        except ValueError as exc:
            assert "fora do diretório" in str(exc)
        else:
            raise AssertionError("symlink para fora do root deveria falhar")
    finally:
        outside.unlink(missing_ok=True)


def test_archive_pending_recovery_json_is_private(tmp_path) -> None:
    cnj_dir = tmp_path / "0001234"
    pending = cnj_dir / "20260630_pending"
    pending.mkdir(parents=True)

    archive_pending(tmp_path, "0001234/20260630_pending", reason="resolvido")

    recovery = tmp_path / "0001234" / "20260630_manual_resolution" / "recovery.json"
    assert stat.S_IMODE(recovery.stat().st_mode) == 0o600
