"""Pilot-driven corpus queue.

Turns real pilot gaps into an auditable queue of accepted corpus sources. This
module deliberately records provenance and coverage metadata before any vector
reingestion happens, so the corpus grows from lawyer-approved evidence rather
than ad hoc files.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from juris.web.pilot_feedback import list_feedback

_FILENAME = "corpus-sources.jsonl"


def sources_path(root: Path) -> Path:
    return root / _FILENAME


def corpus_candidates(root: Path) -> list[dict[str, object]]:
    """Feedback records marked as useful for corpus expansion."""
    accepted_cases = {str(s.get("numero_cnj")) for s in list_accepted_sources(root)}
    candidates: list[dict[str, object]] = []
    for record in list_feedback(root):
        if not record.get("corpus_usable"):
            continue
        numero_cnj = str(record.get("numero_cnj") or "")
        candidates.append(
            {
                "numero_cnj": numero_cnj,
                "output_dir": record.get("output_dir"),
                "missing_source": record.get("missing_source"),
                "notes": record.get("notes"),
                "created_at": record.get("created_at"),
                "accepted": numero_cnj in accepted_cases,
            }
        )
    return candidates


def append_accepted_source(root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Append one lawyer-approved source with mandatory provenance."""
    root.mkdir(parents=True, exist_ok=True)
    content_hash = _resolve_content_hash(payload)
    record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        "content_sha256": content_hash,
        "reingest_status": "pending",
        **{
            k: v
            for k, v in payload.items()
            if k != "source_text" and not (k == "content_sha256" and not v)
        },
    }
    with sources_path(root).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def list_accepted_sources(root: Path) -> list[dict[str, object]]:
    path = sources_path(root)
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
    records.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return records


def coverage_report(root: Path) -> dict[str, object]:
    """Coverage and controlled reingestion report for accepted sources."""
    sources = list_accepted_sources(root)
    candidates = corpus_candidates(root)
    return {
        "accepted_count": len(sources),
        "pending_candidates": [c for c in candidates if not c.get("accepted")],
        "pending_reingest": [s for s in sources if s.get("reingest_status") == "pending"],
        "coverage": {
            "area": _counts(sources, "area"),
            "tema": _counts(sources, "tema"),
            "tribunal": _counts(sources, "tribunal"),
            "source_type": _counts(sources, "source_type"),
            "status": _counts(sources, "status"),
        },
    }


def mark_reingested(root: Path, source_id: str) -> dict[str, object] | None:
    """Mark an accepted source as reingested after the controlled corpus job runs."""
    records = list_accepted_sources(root)
    updated: dict[str, object] | None = None
    now = datetime.now(UTC).isoformat()
    for record in records:
        if record.get("id") == source_id:
            record["reingest_status"] = "done"
            record["reingested_at"] = now
            updated = record
            break
    if updated is None:
        return None
    _rewrite_sources(root, records)
    return updated


def _resolve_content_hash(payload: dict[str, object]) -> str:
    explicit = str(payload.get("content_sha256") or "").strip()
    if explicit:
        return explicit
    text = str(payload.get("source_text") or "").strip()
    if not text:
        msg = "content_sha256 ou source_text é obrigatório para proveniência."
        raise ValueError(msg)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _counts(records: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "").strip() or "não informado"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _rewrite_sources(root: Path, records: list[dict[str, object]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with sources_path(root).open("w", encoding="utf-8") as fh:
        for record in sorted(records, key=lambda r: str(r.get("created_at", ""))):
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
