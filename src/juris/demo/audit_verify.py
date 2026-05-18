"""Audit log verification — backs the `juris audit verify <path>` command.

Re-runs `AuditLog.verify_integrity()` against a JSONL file and returns a
human-readable report. Intended for use by lawyers and ops staff to confirm
that the chain has not been tampered with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from juris.persistence.audit import AuditLog


@dataclass(frozen=True, slots=True)
class AuditVerificationReport:
    """Result of verifying a JSONL audit log."""

    path: Path
    total_entries: int
    corrupted_entry_ids: list[str] = field(default_factory=list)

    @property
    def is_intact(self) -> bool:
        return not self.corrupted_entry_ids

    def to_text(self) -> str:
        lines: list[str] = [f"Audit log: {self.path}"]
        lines.append(f"Total entries: {self.total_entries}")
        if self.is_intact:
            lines.append("Chain integrity: OK")
        else:
            lines.append(
                f"Chain integrity: FAILED ({len(self.corrupted_entry_ids)} corrupted)"
            )
            for cid in self.corrupted_entry_ids:
                lines.append(f"  - {cid}")
        return "\n".join(lines)


def verify_audit_file(path: Path) -> AuditVerificationReport:
    """Verify a JSONL audit file and return a report.

    Raises FileNotFoundError if `path` does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Audit log not found: {path}")
    log = AuditLog(path)
    return AuditVerificationReport(
        path=path,
        total_entries=log.count,
        corrupted_entry_ids=log.verify_integrity(),
    )


__all__ = ["AuditVerificationReport", "verify_audit_file"]
