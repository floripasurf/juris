"""Web-console helpers for controlled filing and receipt recovery."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from juris.core.paths import juris_home, restrict_file
from juris.signing.filing import FilingResult
from juris.web.jsonutil import ensure_dict, ensure_list

_PRIMARY_DRAFTS = frozenset({"draft.md", "rascunho-pesquisa.md"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def default_filing_root() -> Path:
    """Root used by the in-process filing pipeline, overrideable for tests/deploys."""
    configured = os.environ.get("JURIS_FILING_ROOT")
    if configured:
        return Path(configured).expanduser()
    return juris_home() / "filings"


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
            if not _is_regular_file_under(manifest_path, root):
                continue
            manifest = ensure_dict(_read_json(manifest_path))
            case_dir = manifest_path.parent
            request = ensure_dict(manifest.get("request"))
            draft = ensure_dict(manifest.get("draft"))
            listed = ensure_list(manifest.get("artifacts"))
            for artifact in listed:
                if not isinstance(artifact, dict):
                    continue
                name = _primary_artifact_name(str(artifact.get("name") or ""))
                if name is None:
                    continue
                path = (case_dir / name).resolve()
                if not _is_regular_file_under(path, root):
                    continue
                expected_sha = str(artifact.get("sha256") or "")
                if not _sha256_matches(path, expected_sha):
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
                        "sha256": expected_sha,
                        "sha256_verified": True,
                        "grounding_status": draft.get("grounding_status"),
                    }
                )
                if len(artifacts) >= max_items:
                    return {"artifacts": artifacts}
    return {"artifacts": artifacts}


def read_filing_artifact(out_root: Path, *, output_dir: str, artifact_name: str) -> dict[str, object]:
    """Read one primary draft artifact, confined to the tenant output root."""
    name = _primary_artifact_name(artifact_name)
    if name is None:
        msg = "artefato não permitido para protocolo"
        raise ValueError(msg)

    base = out_root.resolve()
    raw = Path(output_dir)
    case_dir = (raw if raw.is_absolute() else base / raw).resolve()
    if not case_dir.is_relative_to(base):
        msg = "artefato fora do diretório de saída permitido"
        raise ValueError(msg)
    path = (case_dir / name).resolve()
    if not _is_regular_file_under(path, base):
        msg = "artefato fora do diretório de saída permitido"
        raise ValueError(msg)
    expected_sha = _manifest_sha_for(case_dir / "run-manifest.json", name)
    if not _sha256_matches(path, expected_sha):
        msg = "hash do artefato não confere com o run-manifest"
        raise ValueError(msg)
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "output_dir": str(case_dir),
        "artifact_name": name,
        "sha256": expected_sha,
        "sha256_verified": True,
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
    signed_pdf = filing_dir / "signed.pdf"
    return {
        "numero_cnj": cnj_dir.name,
        "receipt_id": filing_dir.name,
        "pending_key": f"{cnj_dir.name}/{filing_dir.name}",
        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "signed_pdf_size": signed_pdf.stat().st_size if signed_pdf.exists() else None,
        "hashes": hashes,
        "recovery_actions": [
            "verificar no portal do tribunal se o protocolo foi recebido",
            "se houver protocolo, registrar o recibo manualmente e arquivar o pendente",
            "se não houver protocolo, executar novo protocolo só após confirmar que não houve duplicidade",
        ],
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
        "receipt_key": f"{cnj_dir.name}/{filing_dir.name}",
        "tribunal": metadata.get("tribunal", ""),
        "tipo_documento": metadata.get("tipo_documento", ""),
        "filed_at": metadata.get("filed_at"),
        "protocolo": receipt.get("protocolo"),
        "mensagem": receipt.get("mensagem"),
        "hashes": hashes,
    }


def pending_recovery(root: Path | None, pending_key: str) -> dict[str, object]:
    """Return a recovery plan for one pending filing without exposing signed PDF bytes."""
    root = root or default_filing_root()
    pending = _resolve_pending(root, pending_key)
    cnj_dir = pending.parent
    payload = _pending_payload(cnj_dir, pending)
    payload["status"] = "pending_manual_recovery"
    payload["checklist"] = [
        {"label": "Confirmar no portal se o protocolo existe", "required": True},
        {"label": "Salvar protocolo/recibo externo no caso, se encontrado", "required": True},
        {"label": "Arquivar o pendente somente após conferência humana", "required": True},
    ]
    payload["safe_to_retry"] = False
    payload["retry_note"] = (
        "Retry automático fica bloqueado para evitar protocolo duplicado; reenvie apenas após "
        "confirmar manualmente que o tribunal não recebeu o documento."
    )
    return payload


def archive_pending(root: Path | None, pending_key: str, *, reason: str) -> dict[str, object]:
    """Archive one pending directory after explicit manual resolution."""
    reason = reason.strip()
    if not reason:
        msg = "justificativa é obrigatória para arquivar filing pendente"
        raise ValueError(msg)
    root = root or default_filing_root()
    pending = _resolve_pending(root, pending_key)
    recovery = {
        "archived_at": datetime.now().isoformat(),
        "reason": reason,
        "original_pending_key": pending_key,
    }
    recovery_path = pending / "recovery.json"
    recovery_path.write_text(json.dumps(recovery, indent=2, ensure_ascii=False), encoding="utf-8")
    restrict_file(recovery_path)
    archived = pending.with_name(pending.name.replace("_pending", "_manual_resolution"))
    suffix = 1
    while archived.exists():
        archived = pending.with_name(pending.name.replace("_pending", f"_manual_resolution_{suffix}"))
        suffix += 1
    pending.rename(archived)
    return {
        "archived": True,
        "archived_key": f"{archived.parent.name}/{archived.name}",
        "reason": reason,
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


def _resolve_pending(root: Path, pending_key: str) -> Path:
    base = root.resolve()
    parts = Path(pending_key).parts
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        msg = "chave de filing pendente inválida"
        raise ValueError(msg)
    pending = (base / parts[0] / parts[1]).resolve()
    if not pending.is_relative_to(base):
        msg = "filing pendente fora do diretório permitido"
        raise ValueError(msg)
    if not pending.name.endswith("_pending") or not pending.is_dir():
        msg = "filing pendente não encontrado"
        raise FileNotFoundError(msg)
    return pending


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _primary_artifact_name(name: str) -> str | None:
    """Return an allowed primary artifact name, rejecting path components."""
    candidate = Path(name)
    if candidate.name != name or len(candidate.parts) != 1:
        return None
    return name if name in _PRIMARY_DRAFTS else None


def _manifest_sha_for(manifest_path: Path, artifact_name: str) -> str:
    manifest = ensure_dict(_read_json(manifest_path))
    for artifact in ensure_list(manifest.get("artifacts")):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("name") == artifact_name:
            digest = str(artifact.get("sha256") or "")
            if _SHA256_RE.fullmatch(digest):
                return digest
    msg = "hash do artefato ausente no run-manifest"
    raise ValueError(msg)


def _sha256_matches(path: Path, expected: str) -> bool:
    if not _SHA256_RE.fullmatch(expected):
        return False
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return False
    return h.hexdigest() == expected


def _is_regular_file_under(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.is_relative_to(root) and resolved.is_file()
