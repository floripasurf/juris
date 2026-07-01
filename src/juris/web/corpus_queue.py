"""Pilot-driven corpus queue.

Turns real pilot gaps into an auditable queue of accepted corpus sources. This
module deliberately records provenance and coverage metadata before any vector
reingestion happens, so the corpus grows from lawyer-approved evidence rather
than ad hoc files.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from juris.web.pilot_feedback import list_feedback

_FILENAME = "corpus-sources.jsonl"
_TEXT_DIR = "corpus-source-text"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ReingestReport:
    processed: int
    chunks: int
    errors: list[dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return {
            "processed": self.processed,
            "chunks": self.chunks,
            "errors": self.errors,
        }


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
    if any(str(record.get("content_sha256") or "") == content_hash for record in list_accepted_sources(root)):
        msg = "fonte já aceita no corpus com o mesmo content_sha256."
        raise ValueError(msg)
    source_id = uuid.uuid4().hex
    text_path = _write_source_text(root, source_id, payload)
    record = {
        "id": source_id,
        "created_at": datetime.now(UTC).isoformat(),
        "content_sha256": content_hash,
        "reingest_status": "pending",
        "source_text_path": text_path,
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


def reingest_pending_sources(root: Path, repertory_path: Path) -> ReingestReport:
    """Ingest pending accepted sources into the local FTS repertory."""
    from juris.repertory.chunking import chunk_fonte
    from juris.repertory.corpus.models import TIPO_HIERARQUIA, FonteJurisprudencia, TipoFonte
    from juris.repertory.vector_store import LocalFTSStore

    records = list_accepted_sources(root)
    pending = [r for r in records if r.get("reingest_status") == "pending"]
    if not pending:
        return ReingestReport(processed=0, chunks=0, errors=[])

    store = LocalFTSStore(repertory_path)
    processed = 0
    total_chunks = 0
    errors: list[dict[str, str]] = []
    for record in pending:
        source_id = str(record.get("id") or "")
        try:
            text = _read_source_text(root, record)
            tipo = TipoFonte(str(record.get("source_type") or "acordao_publicado"))
            fonte = FonteJurisprudencia(
                id=f"pilot-{source_id}",
                tribunal=str(record.get("tribunal") or ""),
                tipo=tipo,
                numero=str(record.get("title") or record.get("numero_cnj") or source_id),
                ementa=str(record.get("title") or ""),
                texto_integral=text,
                data_julgamento=_parse_date(str(record.get("source_date") or "")),
                temas=[str(record.get("tema") or "")],
                situacao=str(record.get("status") or "vigente"),
                hierarquia=TIPO_HIERARQUIA.get(tipo, 6),
                source_url=str(record.get("source_url") or ""),
            )
            chunks = chunk_fonte(fonte)
            for chunk in chunks:
                chunk.metadata.update(
                    {
                        "pilot_source_id": source_id,
                        "numero_cnj": record.get("numero_cnj"),
                        "source_url": record.get("source_url"),
                        "source_date": record.get("source_date"),
                        "content_sha256": record.get("content_sha256"),
                        "area": record.get("area"),
                        "tema": record.get("tema"),
                    }
                )
            stored = store.upsert(chunks, [[] for _ in chunks])
            mark_reingested(root, source_id)
            processed += 1
            total_chunks += stored
        except Exception as exc:  # noqa: BLE001 - report per-source failures
            errors.append({"source_id": source_id, "error": str(exc)})
    return ReingestReport(processed=processed, chunks=total_chunks, errors=errors)


def _resolve_content_hash(payload: dict[str, object]) -> str:
    text = str(payload.get("source_text") or "").strip()
    explicit = str(payload.get("content_sha256") or "").strip().lower()
    if explicit:
        if _SHA256_RE.fullmatch(explicit) is None:
            msg = "content_sha256 deve ser um SHA-256 hexadecimal de 64 caracteres."
            raise ValueError(msg)
        if text:
            computed = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if explicit != computed:
                msg = "content_sha256 não confere com source_text."
                raise ValueError(msg)
        return explicit
    if not text:
        msg = "content_sha256 ou source_text é obrigatório para proveniência."
        raise ValueError(msg)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_source_text(root: Path, source_id: str, payload: dict[str, object]) -> str | None:
    text = str(payload.get("source_text") or "").strip()
    if not text:
        return None
    text_dir = root / _TEXT_DIR
    text_dir.mkdir(parents=True, exist_ok=True)
    path = text_dir / f"{source_id}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path.relative_to(root))


def _read_source_text(root: Path, record: dict[str, object]) -> str:
    rel_path = record.get("source_text_path")
    if not rel_path:
        msg = "fonte sem texto local; reingestão automática ainda não disponível só por URL/hash."
        raise RuntimeError(msg)
    path = (root / str(rel_path)).resolve()
    if not path.is_relative_to(root.resolve()):
        msg = "source_text_path fora do diretório do tenant."
        raise RuntimeError(msg)
    return path.read_text(encoding="utf-8")


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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
