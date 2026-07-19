"""Tenant-scoped, privacy-safe operational event ledger for pilot support."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from juris.core.paths import ensure_private_dir, restrict_file
from juris.core.sanitize import safe_error_text

_FILENAME = "operational-events.jsonl"
_MAX_RECENT_EVENTS = 20


def operational_events_path(root: Path) -> Path:
    """Return the private support ledger path for one tenant root."""
    return root / _FILENAME


def append_operational_event(
    root: Path,
    *,
    operation: str,
    code: str,
    message: str,
    status_code: int,
    exc: Exception,
    internal_detail: str | None = None,
    numero_cnj: str | None = None,
) -> dict[str, object]:
    """Append an operational failure without retaining secrets or local paths."""
    ensure_private_dir(root)
    record: dict[str, object] = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        "operation": operation,
        "code": code,
        "message": message,
        "status_code": status_code,
        "exception_type": exc.__class__.__name__,
        "detail": safe_error_text(internal_detail or exc),
    }
    if numero_cnj:
        record["numero_cnj"] = numero_cnj.strip()

    path = operational_events_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    restrict_file(path)
    return record


def list_operational_events(root: Path, *, limit: int = _MAX_RECENT_EVENTS) -> list[dict[str, object]]:
    """List newest ledger events, ignoring a damaged JSONL line rather than failing support."""
    path = operational_events_path(root)
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    records.sort(key=lambda record: str(record.get("created_at", "")), reverse=True)
    return records[: max(0, min(limit, _MAX_RECENT_EVENTS))]


def summarize_operational_events(root: Path) -> dict[str, object]:
    """Return support metrics and a bounded recent-event window for pilot observability."""
    records = list_operational_events(root, limit=_MAX_RECENT_EVENTS)
    all_records = _all_operational_events(root)
    return {
        "total_events": len(all_records),
        "by_operation": _counts(all_records, "operation"),
        "by_code": _counts(all_records, "code"),
        "recent_events": records,
    }


def _all_operational_events(root: Path) -> list[dict[str, object]]:
    path = operational_events_path(root)
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _counts(records: list[dict[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(field, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
