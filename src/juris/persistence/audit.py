"""Audit log — records every AI decision, retrieval, and action."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from juris.core.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """A single audit log entry."""

    entry_id: str
    timestamp: datetime
    event_type: str  # classify, llm_call, sync, analyze, draft, sign, file
    actor: str       # system, llm:claude, llm:ollama, user:<cpf>
    processo_cnj: str | None
    details: dict[str, Any]
    content_hash: str  # SHA-256 of the details for integrity
    prev_hash: str | None = None  # hash of preceding entry (None for first/legacy)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


def _compute_hash(
    timestamp: datetime,
    event_type: str,
    actor: str,
    processo_cnj: str | None,
    details: dict[str, Any],
    prev_hash: str | None = None,
) -> str:
    """SHA-256 hash of the full audit record for integrity verification."""
    payload: dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "event_type": event_type,
        "actor": actor,
        "processo_cnj": processo_cnj,
        "details": details,
    }
    if prev_hash is not None:
        payload["prev_hash"] = prev_hash
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def create_entry(
    event_type: str,
    actor: str,
    details: dict[str, Any],
    processo_cnj: str | None = None,
    prev_hash: str | None = None,
) -> AuditEntry:
    """Create an audit entry with auto-generated ID, timestamp, and hash."""
    timestamp = datetime.now(UTC)
    return AuditEntry(
        entry_id=str(uuid.uuid4()),
        timestamp=timestamp,
        event_type=event_type,
        actor=actor,
        processo_cnj=processo_cnj,
        details=details,
        content_hash=_compute_hash(timestamp, event_type, actor, processo_cnj, details, prev_hash),
        prev_hash=prev_hash,
    )


class AuditLog:
    """Append-only audit log writer.

    Writes to a JSONL file. In production, this will be backed by PostgreSQL.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: AuditEntry) -> None:
        """Append an entry to the audit log.

        Validates that the entry's prev_hash matches the current log tail.
        This prevents callers from bypassing chain construction via log().
        """
        expected_prev = self._get_last_hash()
        if entry.prev_hash != expected_prev:
            msg = (
                f"Chain mismatch: entry.prev_hash={entry.prev_hash!r} "
                f"but log tail is {expected_prev!r}. Use AuditLog.log() to append entries."
            )
            raise ValueError(msg)
        line = json.dumps(entry.to_dict(), ensure_ascii=False, default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.debug("audit_appended", entry_id=entry.entry_id, event_type=entry.event_type)

    def _get_last_hash(self) -> str | None:
        """Read the last entry's content_hash, or None if log is empty."""
        if not self._path.exists():
            return None
        last_line: str | None = None
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
        if last_line is None:
            return None
        return json.loads(last_line)["content_hash"]  # type: ignore[no-any-return]

    def log(
        self,
        event_type: str,
        actor: str,
        details: dict[str, Any],
        processo_cnj: str | None = None,
    ) -> AuditEntry:
        """Create and append an audit entry in one call."""
        prev_hash = self._get_last_hash()
        entry = create_entry(event_type, actor, details, processo_cnj, prev_hash=prev_hash)
        self.append(entry)
        return entry

    def read_all(self) -> list[AuditEntry]:
        """Read all entries from the audit log."""
        if not self._path.exists():
            return []
        entries = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                entries.append(AuditEntry(
                    entry_id=d["entry_id"],
                    timestamp=datetime.fromisoformat(d["timestamp"]),
                    event_type=d["event_type"],
                    actor=d["actor"],
                    processo_cnj=d.get("processo_cnj"),
                    details=d["details"],
                    content_hash=d["content_hash"],
                    prev_hash=d.get("prev_hash"),
                ))
        return entries

    def verify_integrity(self) -> list[str]:
        """Verify all entries have valid content hashes and chain links.

        Legacy entries (prev_hash=None) are allowed only as a contiguous
        block at the start of the log. Once a chained entry appears, all
        subsequent entries must be chained and link to their predecessor.

        Returns list of corrupted entry IDs.
        """
        corrupted = []
        entries = self.read_all()
        chain_started = False
        for i, entry in enumerate(entries):
            # 1. Per-entry hash check (always)
            expected = _compute_hash(
                entry.timestamp,
                entry.event_type,
                entry.actor,
                entry.processo_cnj,
                entry.details,
                prev_hash=entry.prev_hash,
            )
            if expected != entry.content_hash:
                corrupted.append(entry.entry_id)
                continue
            # 2. Chain continuity checks
            if entry.prev_hash is not None:
                chain_started = True
                if i > 0 and entry.prev_hash != entries[i - 1].content_hash:
                    corrupted.append(entry.entry_id)
            elif chain_started:
                # Unchained entry after chain has started — reject
                corrupted.append(entry.entry_id)
        return corrupted

    @property
    def count(self) -> int:
        """Number of entries in the log."""
        if not self._path.exists():
            return 0
        with open(self._path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
