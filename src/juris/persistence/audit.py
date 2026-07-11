"""Audit log — records every AI decision, retrieval, and action."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from juris.core.observability import get_logger
from juris.core.paths import ensure_private_dir, restrict_file

logger = get_logger(__name__)

_ANCHOR_VERSION = 1
_ANCHOR_SENTINEL = "__audit_anchor__"


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


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


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
    raw = _canonical_json(payload)
    return hashlib.sha256(raw.encode()).hexdigest()


def _sign_anchor(payload: dict[str, Any], key: str) -> str:
    return hmac.new(key.encode("utf-8"), _canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()


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

    def __init__(self, path: Path, *, hmac_key: str | None = None) -> None:
        self._path = path
        self._anchor_path = path.with_suffix(path.suffix + ".anchor.json")
        self._hmac_key = hmac_key if hmac_key is not None else os.environ.get("JURIS_AUDIT_HMAC_KEY", "")
        ensure_private_dir(self._path.parent)
        if self._path.exists():
            restrict_file(self._path)
        if self._anchor_path.exists():
            restrict_file(self._anchor_path)

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
        restrict_file(self._path)
        self._write_anchor()
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
        if self._anchor_path.exists() and not self._anchor_valid(entries):
            corrupted.append(_ANCHOR_SENTINEL)
        return corrupted

    def _write_anchor(self) -> None:
        """Persist a signed tail anchor when an HMAC key is configured."""
        if not self._hmac_key:
            return
        entries = self.read_all()
        if not entries:
            return
        payload: dict[str, Any] = {
            "version": _ANCHOR_VERSION,
            "log_name": self._path.name,
            "count": len(entries),
            "first_hash": entries[0].content_hash,
            "tail_hash": entries[-1].content_hash,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        anchor = {**payload, "hmac_sha256": _sign_anchor(payload, self._hmac_key)}
        self._anchor_path.write_text(json.dumps(anchor, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        restrict_file(self._anchor_path)

    def _anchor_valid(self, entries: list[AuditEntry]) -> bool:
        if not self._hmac_key:
            return False
        try:
            anchor_raw = json.loads(self._anchor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(anchor_raw, dict):
            return False
        anchor: dict[str, Any] = anchor_raw
        signature = anchor.pop("hmac_sha256", None)
        if not isinstance(signature, str):
            return False
        if not hmac.compare_digest(signature, _sign_anchor(anchor, self._hmac_key)):
            return False
        if not entries:
            return anchor.get("count") == 0
        return (
            anchor.get("version") == _ANCHOR_VERSION
            and anchor.get("log_name") == self._path.name
            and anchor.get("count") == len(entries)
            and anchor.get("first_hash") == entries[0].content_hash
            and anchor.get("tail_hash") == entries[-1].content_hash
        )

    @property
    def count(self) -> int:
        """Number of entries in the log."""
        if not self._path.exists():
            return 0
        with open(self._path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
