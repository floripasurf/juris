"""Web-console helpers for controlled filing and receipt recovery."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from juris.signing.filing import FilingResult

_PRIMARY_DRAFTS = frozenset({"draft.md", "rascunho-pesquisa.md"})


def default_filing_root() -> Path:
    """Root used by the in-process filing pipeline, overrideable for tests/deploys."""
    configured = os.environ.get("JURIS_FILING_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".juris" / "filings"


def filing_status(root: Path | None = None) -> dict[str, object]:
    """Return pending filings and recent receipts visible to the console."""
    root = root or default_filing_root()
    pending: list[dict[str, object]] = []
    receipts: list[dict[str, object]] = []
    if root.exists():
        for cnj_dir in sorted(root.iterdir()):
            if not cnj_dir.is_dir():
                continue
            for filing_dir in sorted(cnj_dir.iterdir()):
                if not filing_dir.is_dir():
                    continue
                if filing_dir.name.endswith("_pending"):
                    pending.append(_pending_payload(cnj_dir, filing_dir))
                else:
                    receipt = _receipt_payload(cnj_dir, filing_dir)
                    if receipt is not None:
                        receipts.append(receipt)

    receipts.sort(key=lambda r: str(r.get("filed_at") or ""), reverse=True)
    pending.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {
        "filing_root": str(root),
        "pending": pending,
        "recent_receipts": receipts[:20],
    }


def filing_artifacts(out_root: Path, *, max_items: int = 20) -> dict[str, object]:
    """Return recent primary draft artifacts that can seed the filing form."""
    root = out_root.resolve()
    artifacts: list[dict[str, object]] = []
    if root.exists():
        manifests = sorted(
            root.glob("*/run-manifest.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for manifest_path in manifests:
            manifest = _read_json(manifest_path)
            case_dir = manifest_path.parent
            request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
            draft = manifest.get("draft") if isinstance(manifest.get("draft"), dict) else {}
            listed = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []
            for artifact in listed:
                if not isinstance(artifact, dict):
                    continue
                name = str(artifact.get("name") or "")
                if name not in _PRIMARY_DRAFTS:
                    continue
                path = case_dir / name
                if not path.exists():
                    continue
                artifacts.append(
                    {
                        "numero_cnj": request.get("numero_cnj"),
                        "tribunal": request.get("tribunal"),
                        "tipo_peticao": request.get("tipo_peticao"),
                        "output_mode": manifest.get("output_mode"),
                        "finished_at": manifest.get("finished_at"),
                        "output_dir": str(case_dir),
                        "artifact_name": name,
                        "sha256": artifact.get("sha256"),
                        "grounding_status": draft.get("grounding_status"),
                    }
                )
                if len(artifacts) >= max_items:
                    return {"artifacts": artifacts}
    return {"artifacts": artifacts}


def read_filing_artifact(out_root: Path, *, output_dir: str, artifact_name: str) -> dict[str, object]:
    """Read one primary draft artifact, confined to the tenant output root."""
    name = Path(artifact_name).name
    if name not in _PRIMARY_DRAFTS:
        msg = "artefato não permitido para protocolo"
        raise ValueError(msg)

    base = out_root.resolve()
    raw = Path(output_dir)
    case_dir = (raw if raw.is_absolute() else base / raw).resolve()
    if not case_dir.is_relative_to(base):
        msg = "artefato fora do diretório de saída permitido"
        raise ValueError(msg)
    path = (case_dir / name).resolve()
    if not path.is_relative_to(base):
        msg = "artefato fora do diretório de saída permitido"
        raise ValueError(msg)
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "output_dir": str(case_dir),
        "artifact_name": name,
        "content": text,
    }


def serialize_filing_result(result: FilingResult) -> dict[str, object]:
    """Serialize a filing result without exposing PDF bytes or secrets."""
    return {
        "success": result.success,
        "error": result.error,
        "audit_entry_ids": list(result.audit_entry_ids),
        "preflight": _preflight_payload(result.preflight),
        "receipt": _receipt_metadata(result.receipt),
        "signing": (
            {
                "signer_name": result.signing_result.signer_name,
                "signer_cpf": result.signing_result.signer_cpf,
                "signed_at": result.signing_result.timestamp.isoformat(),
                "pdf_hash": result.signing_result.pdf_hash,
                "signed_pdf_hash": result.signing_result.signed_pdf_hash,
            }
            if result.signing_result is not None
            else None
        ),
        "chain_of_custody": (
            {
                "pdf_hash": result.chain_of_custody.pdf_hash,
                "signed_pdf_hash": result.chain_of_custody.signed_pdf_hash,
                "submitted_payload_hash": result.chain_of_custody.submitted_payload_hash,
                "receipt_hash": result.chain_of_custody.receipt_hash,
            }
            if result.chain_of_custody is not None
            else None
        ),
    }


def _pending_payload(cnj_dir: Path, filing_dir: Path) -> dict[str, object]:
    stat = filing_dir.stat()
    hashes = _read_json(filing_dir / "hashes.json")
    return {
        "numero_cnj": cnj_dir.name,
        "receipt_id": filing_dir.name,
        "path": str(filing_dir),
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "hashes": hashes,
    }


def _receipt_payload(cnj_dir: Path, filing_dir: Path) -> dict[str, object] | None:
    receipt = _read_json(filing_dir / "receipt.json")
    if not receipt:
        return None
    metadata = _read_json(filing_dir / "metadata.json")
    hashes = _read_json(filing_dir / "hashes.json")
    return {
        "numero_cnj": receipt.get("numero_processo") or cnj_dir.name,
        "receipt_id": filing_dir.name,
        "path": str(filing_dir),
        "tribunal": metadata.get("tribunal", ""),
        "tipo_documento": metadata.get("tipo_documento", ""),
        "filed_at": metadata.get("filed_at"),
        "protocolo": receipt.get("protocolo"),
        "mensagem": receipt.get("mensagem"),
        "hashes": hashes,
    }


def _receipt_metadata(receipt: Any | None) -> dict[str, object] | None:
    if receipt is None:
        return None
    return {
        "sucesso": receipt.sucesso,
        "mensagem": receipt.mensagem,
        "protocolo": receipt.protocolo,
        "data_recebimento": receipt.data_recebimento.isoformat() if receipt.data_recebimento else None,
        "numero_processo": receipt.numero_processo,
        "pdf_hash": receipt.pdf_hash,
    }


def _preflight_payload(preflight: Any | None) -> dict[str, object] | None:
    if preflight is None:
        return None
    checks = [
        {
            "name": check.name,
            "passed": check.passed,
            "severity": check.severity,
            "message": check.message,
            "retryable": check.retryable,
        }
        for check in preflight.checks
    ]
    return {
        "passed": preflight.passed,
        "prazo_status": preflight.prazo_status.value,
        "blockers": [c for c in checks if not c["passed"] and c["severity"] == "blocker"],
        "checks": checks,
    }


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
