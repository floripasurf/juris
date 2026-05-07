"""Tests for filing receipt storage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from juris.mni.operations.peticionamento import FilingReceipt
from juris.persistence.audit import AuditLog
from juris.persistence.filing_receipt import FilingReceiptStore, StoredReceipt

CNJ = "1234567-89.2026.8.13.0001"
SIGNED_PDF = b"%PDF-fake-signed-content"
RENDER_HASH = "abc123render"
PAYLOAD_HASH = "def456payload"


def _make_store(tmp_path: Path) -> FilingReceiptStore:
    audit = AuditLog(tmp_path / "audit.jsonl")
    return FilingReceiptStore(tmp_path / "filings", audit)


def _make_receipt(
    protocolo: str = "PROT-2026-001",
    sucesso: bool = True,
) -> FilingReceipt:
    return FilingReceipt(
        sucesso=sucesso,
        mensagem="OK" if sucesso else "Falha",
        protocolo=protocolo,
        data_recebimento=datetime(2026, 5, 6, 10, 30),
        numero_processo=CNJ,
        pdf_hash="pdfhash123",
    )


class TestPrepare:
    def test_creates_pending_directory_with_signed_pdf(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        pending = Path(pending_path)

        assert pending.exists()
        assert pending.name.endswith("_pending")
        assert (pending / "signed.pdf").read_bytes() == SIGNED_PDF

    def test_creates_hashes_json(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        pending = Path(pending_path)

        hashes = json.loads((pending / "hashes.json").read_text())
        assert hashes["pdf_hash"] == RENDER_HASH
        assert "signed_pdf_hash" in hashes


class TestConfirm:
    def test_renames_pending_to_final(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        receipt = _make_receipt()

        receipt_id = store.confirm(
            pending_path, receipt, PAYLOAD_HASH, tribunal="TJMG", tipo_documento="peticao"
        )

        # Pending directory should no longer exist
        assert not Path(pending_path).exists()
        # Final directory should exist
        final_dir = Path(pending_path).parent / receipt_id
        assert final_dir.exists()
        assert (final_dir / "receipt.json").exists()
        assert (final_dir / "hashes.json").exists()
        assert (final_dir / "metadata.json").exists()

    def test_raises_for_nonexistent_pending_path(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        receipt = _make_receipt()

        with pytest.raises(FileNotFoundError):
            store.confirm("/nonexistent/path", receipt, PAYLOAD_HASH)

    def test_atomic_rename_contains_timestamp_and_protocolo(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        receipt = _make_receipt(protocolo="PROT-2026-001")

        receipt_id = store.confirm(pending_path, receipt, PAYLOAD_HASH)

        assert "PROT-2026-001" in receipt_id  # hyphens are allowed by sanitizer
        # Timestamp prefix preserved
        timestamp_prefix = Path(pending_path).name.replace("_pending", "")
        assert receipt_id.startswith(timestamp_prefix)

    def test_chain_of_custody_hashes_complete(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        receipt = _make_receipt()

        receipt_id = store.confirm(pending_path, receipt, PAYLOAD_HASH)
        final_dir = Path(pending_path).parent / receipt_id
        hashes = json.loads((final_dir / "hashes.json").read_text())

        assert hashes["pdf_hash"] == RENDER_HASH
        assert "signed_pdf_hash" in hashes
        assert hashes["submitted_payload_hash"] == PAYLOAD_HASH
        assert "receipt_hash" in hashes


class TestGet:
    def test_retrieves_confirmed_receipt(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        receipt = _make_receipt()
        receipt_id = store.confirm(
            pending_path, receipt, PAYLOAD_HASH, tribunal="TJMG", tipo_documento="peticao"
        )

        stored = store.get(CNJ, receipt_id)

        assert stored is not None
        assert isinstance(stored, StoredReceipt)
        assert stored.receipt_id == receipt_id
        assert stored.numero_cnj == CNJ
        assert stored.tribunal == "TJMG"
        assert stored.tipo_documento == "peticao"
        assert stored.protocolo == "PROT-2026-001"
        assert stored.receipt.sucesso is True

    def test_returns_none_for_nonexistent(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get(CNJ, "nonexistent_receipt") is None


class TestListByProcesso:
    def test_returns_all_confirmed_receipts_sorted(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # Create two confirmed receipts
        p1 = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        r1 = _make_receipt(protocolo="PROT-001")
        id1 = store.confirm(p1, r1, PAYLOAD_HASH)

        p2 = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        r2 = _make_receipt(protocolo="PROT-002")
        id2 = store.confirm(p2, r2, PAYLOAD_HASH)

        results = store.list_by_processo(CNJ)

        assert len(results) == 2
        assert results[0].receipt_id == id1
        assert results[1].receipt_id == id2

    def test_excludes_pending_directories(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # One confirmed, one still pending
        p1 = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        store.confirm(p1, _make_receipt(), PAYLOAD_HASH)
        store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)  # left pending

        results = store.list_by_processo(CNJ)
        assert len(results) == 1

    def test_returns_empty_for_unknown_processo(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.list_by_processo("0000000-00.0000.0.00.0000") == []


class TestRecoverPending:
    def test_finds_pending_directories(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        pending_path = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)

        pending = store.recover_pending()

        assert len(pending) == 1
        assert pending[0] == pending_path

    def test_returns_empty_when_no_pending(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # Prepare and confirm — nothing left pending
        p = store.prepare(CNJ, SIGNED_PDF, RENDER_HASH)
        store.confirm(p, _make_receipt(), PAYLOAD_HASH)

        assert store.recover_pending() == []
