"""Immutable storage of filing receipts with crash recovery via atomic rename."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from juris.core.observability import get_logger
from juris.core.paths import ensure_private_dir, restrict_file
from juris.mni.operations.peticionamento import FilingReceipt
from juris.persistence.audit import AuditLog

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    """A stored filing receipt with metadata."""

    receipt_id: str
    numero_cnj: str
    tribunal: str
    tipo_documento: str
    protocolo: str | None
    filed_at: datetime
    receipt: FilingReceipt
    hashes: dict[str, str]  # chain-of-custody hashes
    storage_path: Path


class FilingReceiptStore:
    """Immutable storage of filing receipts.

    Uses atomic rename for crash recovery: files are first written to
    a _pending directory, then renamed to _<protocolo> after MNI confirmation.
    """

    def __init__(self, storage_dir: Path, audit: AuditLog) -> None:
        self._storage_dir = storage_dir
        self._audit = audit
        ensure_private_dir(self._storage_dir)
        self._storage_root = self._storage_dir.resolve()

    def prepare(self, numero_cnj: str, signed_pdf: bytes, render_hash: str) -> str:
        """Create pending filing directory with signed PDF.

        Creates ~/.juris/filings/<cnj>/<timestamp>_pending/
        Writes signed PDF + metadata.

        Returns:
            pending_path as string
        """
        cnj_dir = self._cnj_to_dirname(numero_cnj)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        nonce = uuid.uuid4().hex[:8]
        processo_dir = self._storage_dir / cnj_dir
        ensure_private_dir(processo_dir)
        pending_dir = processo_dir / f"{timestamp}_{nonce}_pending"
        ensure_private_dir(pending_dir)

        # Write signed PDF
        self._write_bytes_private(pending_dir / "signed.pdf", signed_pdf)

        # Write initial hashes
        signed_hash = hashlib.sha256(signed_pdf).hexdigest()
        hashes = {
            "pdf_hash": render_hash,
            "signed_pdf_hash": signed_hash,
        }
        self._write_json_private(pending_dir / "hashes.json", hashes)

        self._audit.log(
            event_type="filing.receipt_prepared",
            actor="system",
            details={
                "pending_id": pending_dir.name,
                "pending_receipt": True,
                "signed_pdf_hash": signed_hash,
            },
            processo_cnj=numero_cnj,
        )

        return str(pending_dir)

    def confirm(
        self,
        pending_path: str,
        receipt: FilingReceipt,
        submitted_payload_hash: str,
        tribunal: str = "",
        tipo_documento: str = "",
    ) -> str:
        """Confirm filing by atomic rename and storing receipt.

        Atomic rename: <timestamp>_pending/ -> <timestamp>_<protocolo>/
        Writes receipt JSON + final chain-of-custody hashes.

        Returns:
            receipt_id (the final directory name)
        """
        pending = self._resolve_pending_path(pending_path)
        if not pending.exists():
            msg = f"Pending path does not exist: {pending_path}"
            raise FileNotFoundError(msg)
        if not pending.is_dir() or not pending.name.endswith("_pending"):
            msg = f"Invalid pending filing directory: {pending_path}"
            raise ValueError(msg)
        ensure_private_dir(pending, restrict_existing=True)

        # Build final directory name
        timestamp_prefix = pending.name.removesuffix("_pending")
        protocolo = receipt.protocolo or "no_protocolo"
        safe_protocolo = self._safe_segment(protocolo, fallback="no_protocolo")
        receipt_id = f"{timestamp_prefix}_{safe_protocolo}"
        final_dir = pending.parent / receipt_id
        if final_dir.exists():
            msg = f"Receipt directory already exists: {final_dir}"
            raise FileExistsError(msg)

        # Write receipt JSON before rename
        receipt_data = {
            "sucesso": receipt.sucesso,
            "mensagem": receipt.mensagem,
            "protocolo": receipt.protocolo,
            "data_recebimento": (
                receipt.data_recebimento.isoformat() if receipt.data_recebimento else None
            ),
            "numero_processo": receipt.numero_processo,
            "pdf_hash": receipt.pdf_hash,
        }
        self._write_json_private(pending / "receipt.json", receipt_data)

        # Update hashes with full chain of custody
        hashes_path = pending / "hashes.json"
        hashes = json.loads(hashes_path.read_text(encoding="utf-8")) if hashes_path.exists() else {}
        receipt_hash = hashlib.sha256(
            json.dumps(receipt_data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        hashes["submitted_payload_hash"] = submitted_payload_hash
        hashes["receipt_hash"] = receipt_hash
        self._write_json_private(hashes_path, hashes)

        # Write metadata
        metadata = {
            "tribunal": tribunal,
            "tipo_documento": tipo_documento,
            "filed_at": datetime.now().isoformat(),
        }
        self._write_json_private(pending / "metadata.json", metadata)

        # Atomic rename
        pending.rename(final_dir)

        self._audit.log(
            event_type="filing.receipt_confirmed",
            actor="system",
            details={
                "receipt_id": receipt_id,
                "protocolo": receipt.protocolo,
                "hashes": hashes,
            },
            processo_cnj=receipt.numero_processo,
        )

        return receipt_id

    def get(self, numero_cnj: str, receipt_id: str) -> StoredReceipt | None:
        """Retrieve a stored receipt by CNJ and receipt_id."""
        cnj_dir = self._storage_dir / self._cnj_to_dirname(numero_cnj)
        receipt_dir = self._receipt_dir(cnj_dir, receipt_id)
        if not receipt_dir.exists():
            return None
        return self._load_receipt(receipt_dir, numero_cnj)

    def list_by_processo(self, numero_cnj: str) -> list[StoredReceipt]:
        """List all receipts for a processo."""
        cnj_dir = self._storage_dir / self._cnj_to_dirname(numero_cnj)
        if not cnj_dir.exists():
            return []
        receipts = []
        for d in sorted(cnj_dir.iterdir()):
            if d.is_dir() and not d.name.endswith("_pending"):
                stored = self._load_receipt(d, numero_cnj)
                if stored:
                    receipts.append(stored)
        return receipts

    def recover_pending(self) -> list[str]:
        """Find _pending directories from interrupted filings."""
        pending: list[str] = []
        if not self._storage_dir.exists():
            return pending
        for cnj_dir in self._storage_dir.iterdir():
            if not cnj_dir.is_dir():
                continue
            for d in cnj_dir.iterdir():
                if d.is_dir() and d.name.endswith("_pending"):
                    pending.append(str(d))
        return pending

    def _load_receipt(self, receipt_dir: Path, numero_cnj: str) -> StoredReceipt | None:
        """Load a StoredReceipt from a directory."""
        receipt_path = receipt_dir / "receipt.json"
        if not receipt_path.exists():
            return None

        receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
        hashes_path = receipt_dir / "hashes.json"
        hashes = json.loads(hashes_path.read_text(encoding="utf-8")) if hashes_path.exists() else {}
        metadata_path = receipt_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}

        data_recebimento = None
        if receipt_data.get("data_recebimento"):
            data_recebimento = datetime.fromisoformat(receipt_data["data_recebimento"])

        filing_receipt = FilingReceipt(
            sucesso=receipt_data.get("sucesso", False),
            mensagem=receipt_data.get("mensagem", ""),
            protocolo=receipt_data.get("protocolo"),
            data_recebimento=data_recebimento,
            numero_processo=receipt_data.get("numero_processo"),
            pdf_hash=receipt_data.get("pdf_hash"),
        )

        filed_at_str = metadata.get("filed_at")
        filed_at = datetime.fromisoformat(filed_at_str) if filed_at_str else datetime.now()

        return StoredReceipt(
            receipt_id=receipt_dir.name,
            numero_cnj=numero_cnj,
            tribunal=metadata.get("tribunal", ""),
            tipo_documento=metadata.get("tipo_documento", ""),
            protocolo=receipt_data.get("protocolo"),
            filed_at=filed_at,
            receipt=filing_receipt,
            hashes=hashes,
            storage_path=receipt_dir,
        )

    @staticmethod
    def _cnj_to_dirname(numero_cnj: str) -> str:
        """Sanitize CNJ number for use as directory name."""
        normalized = numero_cnj.replace(".", "_").replace("-", "_")
        return FilingReceiptStore._safe_segment(normalized, fallback="unknown_cnj")

    @staticmethod
    def _safe_segment(value: str, *, fallback: str) -> str:
        """Return a path-safe single directory segment."""
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
        return cleaned or fallback

    @staticmethod
    def _write_bytes_private(path: Path, data: bytes) -> None:
        path.write_bytes(data)
        restrict_file(path)

    @staticmethod
    def _write_json_private(path: Path, data: object) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        restrict_file(path)

    def _resolve_pending_path(self, pending_path: str) -> Path:
        pending = Path(pending_path).expanduser()
        try:
            resolved = pending.resolve()
        except OSError as exc:
            msg = f"Invalid pending path: {pending_path}"
            raise ValueError(msg) from exc
        if not resolved.is_relative_to(self._storage_root):
            msg = "Pending path is outside filing storage root."
            raise ValueError(msg)
        return resolved

    def _receipt_dir(self, cnj_dir: Path, receipt_id: str) -> Path:
        if not receipt_id or receipt_id != self._safe_segment(receipt_id, fallback=""):
            msg = "Invalid receipt_id."
            raise ValueError(msg)
        return cnj_dir / receipt_id
