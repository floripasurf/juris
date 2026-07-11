"""Audit viewer for the operator console (console #3).

Reads a case's ``audit.jsonl``, runs the same integrity check as
``juris audit verify``, and returns the chain — entries + verdict — for the UI,
so the lawyer can confirm on screen that nothing was tampered with.
"""

from __future__ import annotations

import os
from pathlib import Path

from juris.demo.audit_verify import verify_audit_file
from juris.persistence.audit import AuditLog


def resolve_audit_path(output_dir: str, *, root: Path | None = None) -> Path:
    """Resolve ``<output_dir>/audit.jsonl``, confined to the output root.

    Prevents the audit endpoint from reading arbitrary local files: the resolved
    path must live under ``root`` (default ``$JURIS_OUT_ROOT`` or ``juris-out``).

    Raises:
        ValueError: if the path escapes the root (traversal).
    """
    base = (root or Path(os.environ.get("JURIS_OUT_ROOT", "juris-out"))).resolve()
    raw = Path(output_dir)
    candidate = (raw if raw.is_absolute() else base / raw).resolve()
    if not candidate.is_relative_to(base):
        msg = "caminho de auditoria fora do diretório de saída permitido"
        raise ValueError(msg)
    return candidate / "audit.jsonl"


def audit_view(path: Path) -> dict[str, object]:
    """Return the audit chain + verification verdict for ``path``.

    Raises:
        FileNotFoundError: if the audit log doesn't exist.
    """
    report = verify_audit_file(path)  # raises FileNotFoundError if absent
    corrupted = set(report.corrupted_entry_ids)
    entries = [
        {
            "entry_id": entry.entry_id,
            "timestamp": entry.timestamp.isoformat(),
            "event_type": entry.event_type,
            "actor": entry.actor,
            "processo_cnj": entry.processo_cnj,
            "details_keys": sorted(entry.details.keys()),
            "corrupted": entry.entry_id in corrupted,
        }
        for entry in AuditLog(path).read_all()
    ]
    return {
        "audit_file": path.name,
        "total": report.total_entries,
        "intact": report.is_intact,
        "corrupted": report.corrupted_entry_ids,
        "entries": entries,
    }
