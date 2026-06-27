"""Audit viewer for the operator console (console #3).

Reads a case's ``audit.jsonl``, runs the same integrity check as
``juris audit verify``, and returns the chain — entries + verdict — for the UI,
so the lawyer can confirm on screen that nothing was tampered with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from juris.demo.audit_verify import verify_audit_file
from juris.persistence.audit import AuditLog

if TYPE_CHECKING:
    from pathlib import Path


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
        "path": str(path),
        "total": report.total_entries,
        "intact": report.is_intact,
        "corrupted": report.corrupted_entry_ids,
        "entries": entries,
    }
