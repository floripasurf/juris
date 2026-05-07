"""Differential read — fetch only new movements for a processo.

Compares the last stored movement timestamp against fresh MNI data
to detect and persist only new movements and documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from juris.core.observability import get_logger
from juris.mni.parsers.processo import Movimento, ProcessoDomain, parse_processo

logger = get_logger(__name__)


@dataclass(slots=True)
class DiffResult:
    """Result of a differential read for one processo."""

    numero_cnj: str
    tribunal_id: str
    new_movimentos: list[Movimento] = field(default_factory=list)
    new_documento_ids: list[str] = field(default_factory=list)
    total_movimentos_fetched: int = 0
    had_changes: bool = False
    error: str | None = None

    @property
    def summary(self) -> str:
        if self.error:
            return f"[ERROR] {self.numero_cnj}: {self.error}"
        if not self.had_changes:
            return f"[OK] {self.numero_cnj}: no changes"
        return (
            f"[UPDATED] {self.numero_cnj}: "
            f"{len(self.new_movimentos)} new movements, "
            f"{len(self.new_documento_ids)} new documents"
        )


def detect_new_movements(
    fetched: ProcessoDomain,
    last_sync_at: datetime | None,
    known_movimento_keys: set[tuple[datetime, int | None, str | None]] | None = None,
) -> list[Movimento]:
    """Detect movements that are new since the last sync.

    Uses a two-layer approach:
    1. Timestamp filter: skip movements older than last_sync_at
    2. Key dedup: skip movements with known (data_hora, codigo_nacional, id_movimento) tuples

    Args:
        fetched: The freshly parsed ProcessoDomain from MNI.
        last_sync_at: Timestamp of the last successful sync (None = first sync).
        known_movimento_keys: Set of (data_hora, codigo, id) tuples already in DB.

    Returns:
        List of Movimento objects that are new.
    """
    if last_sync_at is None:
        return fetched.movimentos  # First sync — everything is new

    known = known_movimento_keys or set()
    new_movs: list[Movimento] = []

    for mov in fetched.movimentos:
        # Timestamp-based fast filter
        mov_time = mov.data_hora
        if mov_time.tzinfo is None:
            # Treat naive as UTC for comparison
            from datetime import timezone
            mov_time = mov_time.replace(tzinfo=timezone.utc)

        last_sync_aware = last_sync_at
        if last_sync_aware.tzinfo is None:
            from datetime import timezone
            last_sync_aware = last_sync_aware.replace(tzinfo=timezone.utc)

        if mov_time < last_sync_aware:
            continue

        # Key-based dedup
        key = (mov.data_hora, mov.codigo_nacional, mov.id_movimento)
        if key in known:
            continue

        new_movs.append(mov)

    return new_movs


def detect_new_documents(
    fetched: ProcessoDomain,
    known_doc_ids: set[str],
) -> list[str]:
    """Detect documents not yet stored.

    Args:
        fetched: The freshly parsed ProcessoDomain.
        known_doc_ids: Set of id_documento strings already stored.

    Returns:
        List of new document id_documento values.
    """
    return [
        doc.id_documento
        for doc in fetched.documentos
        if doc.id_documento and doc.id_documento not in known_doc_ids
    ]


def diff_processo(
    fetched: ProcessoDomain,
    last_sync_at: datetime | None,
    known_movimento_keys: set[tuple[datetime, int | None, str | None]] | None = None,
    known_doc_ids: set[str] | None = None,
) -> DiffResult:
    """Run a full differential comparison for a processo.

    Args:
        fetched: Freshly fetched ProcessoDomain.
        last_sync_at: When the processo was last synced.
        known_movimento_keys: Existing movement keys from DB.
        known_doc_ids: Existing document IDs from DB.

    Returns:
        DiffResult with new movements and documents.
    """
    new_movs = detect_new_movements(fetched, last_sync_at, known_movimento_keys)
    new_docs = detect_new_documents(fetched, known_doc_ids or set())

    result = DiffResult(
        numero_cnj=fetched.numero_cnj,
        tribunal_id=fetched.tribunal or "unknown",
        new_movimentos=new_movs,
        new_documento_ids=new_docs,
        total_movimentos_fetched=len(fetched.movimentos),
        had_changes=bool(new_movs or new_docs),
    )

    logger.info(
        "diff_resultado",
        numero_cnj=result.numero_cnj,
        new_movs=len(new_movs),
        new_docs=len(new_docs),
        total_fetched=result.total_movimentos_fetched,
    )

    return result
