"""Seed loader for local JSON corpus files.

Loads jurisprudence data from JSON files in data/corpus/,
converts to FonteJurisprudencia, chunks, and ingests into the vector store.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.corpus.status import is_active
from juris.repertory.embeddings import LegalEmbedder
from juris.repertory.ingestion.base import CorpusIngester, IngestionResult
from juris.repertory.vector_store import VectorStore

if TYPE_CHECKING:
    from juris.persistence.audit import AuditLog

logger = logging.getLogger(__name__)

_DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[4] / "data" / "corpus"

_FILE_TYPE_MAP: dict[str, tuple[TipoFonte, str, int]] = {
    "sumulas_vinculantes.json": (TipoFonte.SUMULA_VINCULANTE, "STF", 1),
    "temas_repercussao_geral_stf.json": (TipoFonte.RE_STF, "STF", 2),
    "temas_repetitivos_stj.json": (TipoFonte.RESP_REPETITIVO, "STJ", 3),
    "sumulas_stf.json": (TipoFonte.SUMULA, "STF", 4),
    "sumulas_stj.json": (TipoFonte.SUMULA, "STJ", 4),
    "sumulas_tst.json": (TipoFonte.SUMULA, "TST", 4),
    "ojs_tst.json": (TipoFonte.JURISPRUDENCIA_UNIFORME, "TST", 5),
}


class SeedLoader(CorpusIngester):
    """Loads JSON seed files from data/corpus/.

    Args:
        corpus_dir: Path to the corpus directory.
    """

    def __init__(self, corpus_dir: Path | None = None, include_superseded: bool = False) -> None:
        self._corpus_dir = corpus_dir or _DEFAULT_CORPUS_DIR
        self._include_superseded = include_superseded

    def fetch(self) -> list[FonteJurisprudencia]:
        """Load all JSON files from the corpus directory.

        Returns:
            List of FonteJurisprudencia from all seed files.
        """
        fontes: list[FonteJurisprudencia] = []
        if not self._corpus_dir.exists():
            logger.warning("Corpus directory not found: %s", self._corpus_dir)
            return fontes

        for filename, (tipo, tribunal, hierarquia) in _FILE_TYPE_MAP.items():
            filepath = self._corpus_dir / filename
            if not filepath.exists():
                logger.debug("Seed file not found: %s", filepath)
                continue

            with filepath.open(encoding="utf-8") as f:
                entries = json.load(f)

            for entry in entries:
                fonte = self._entry_to_fonte(entry, tipo, tribunal, hierarquia)
                if fonte and (self._include_superseded or is_active(fonte.tipo, fonte.situacao)):
                    fontes.append(fonte)

            logger.info("Loaded %d entries from %s", len(entries), filename)

        return fontes

    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a FonteJurisprudencia into document chunks.

        Args:
            raw: A FonteJurisprudencia instance.

        Returns:
            List of document chunks.
        """
        if not isinstance(raw, FonteJurisprudencia):
            return []
        return chunk_fonte(raw)

    def ingest(
        self,
        vector_store: VectorStore,
        embedder: LegalEmbedder | None = None,
        audit_log: AuditLog | None = None,
    ) -> IngestionResult:
        """Full ingestion pipeline: fetch -> chunk -> embed -> store.

        Args:
            vector_store: Target vector store.
            embedder: Optional embedder (if None, stores without embeddings).
            audit_log: Optional audit log for forensic event recording.

        Returns:
            IngestionResult with counts.
        """
        start_ts = datetime.now(UTC)
        fontes = self.fetch()
        all_chunks: list[DocumentChunk] = []
        for fonte in fontes:
            all_chunks.extend(self.parse(fonte))

        if not all_chunks:
            return IngestionResult(
                total_fetched=len(fontes), total_chunks=0, total_embedded=0
            )

        # Generate embeddings if embedder available
        texts = [c.text for c in all_chunks]
        embeddings = embedder.embed_texts(texts) if embedder is not None else None

        # Store chunks
        if embeddings is not None:
            stored = vector_store.upsert(all_chunks, embeddings)
        else:
            # Use zero vectors as placeholder for FTS-only stores
            dim = embedder.dimension if embedder else 1024
            zero_embeddings = [[0.0] * dim for _ in all_chunks]
            stored = vector_store.upsert(all_chunks, zero_embeddings)

        logger.info(
            "Ingested %d fontes -> %d chunks -> %d stored",
            len(fontes),
            len(all_chunks),
            stored,
        )

        if audit_log is not None:
            self._emit_audit(audit_log, fontes, all_chunks, stored, embedder, start_ts)

        return IngestionResult(
            total_fetched=len(fontes),
            total_chunks=len(all_chunks),
            total_embedded=stored,
        )

    def _emit_audit(
        self,
        audit_log: AuditLog,
        fontes: list[FonteJurisprudencia],
        chunks: list[DocumentChunk],
        stored: int,
        embedder: LegalEmbedder | None,
        start_ts: datetime,
    ) -> None:
        """Emit a forensic audit event for corpus ingestion."""
        source_files: dict[str, dict[str, Any]] = {}
        total_entries_read = 0
        for filename in _FILE_TYPE_MAP:
            filepath = self._corpus_dir / filename
            if filepath.exists():
                raw = filepath.read_bytes()
                entries = json.loads(raw)
                total_entries_read += len(entries)
                source_files[filename] = {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                    "entry_count": len(entries),
                }

        audit_log.log(
            event_type="corpus.ingest",
            actor="system",
            details={
                "corpus_dir": str(self._corpus_dir),
                "include_superseded": self._include_superseded,
                "source_files": source_files,
                "total_fetched": len(fontes),
                "skipped_count": total_entries_read - len(fontes),
                "total_chunks": len(chunks),
                "total_stored": stored,
                "embedder_version": getattr(embedder, "model_name", None),
                "input_hash": hashlib.sha256(
                    json.dumps(
                        [f.id for f in fontes], sort_keys=True,
                    ).encode()
                ).hexdigest(),
                "started_at": start_ts.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )

    @staticmethod
    def _entry_to_fonte(
        entry: dict[str, Any],
        tipo: TipoFonte,
        tribunal: str,
        hierarquia: int,
    ) -> FonteJurisprudencia | None:
        """Convert a JSON entry to FonteJurisprudencia.

        Args:
            entry: JSON dictionary.
            tipo: Type of source.
            tribunal: Court identifier.
            hierarquia: Hierarchy level.

        Returns:
            FonteJurisprudencia or None if entry is invalid.
        """
        numero = entry.get("numero", "")
        texto = entry.get("texto") or entry.get("tese") or entry.get("descricao", "")
        if not texto:
            return None

        source_id = f"{tipo.value}_{tribunal}_{numero}"

        data_aprovacao: date | None = None
        if raw_date := entry.get("data_aprovacao"):
            with contextlib.suppress(ValueError, TypeError):
                data_aprovacao = date.fromisoformat(raw_date)

        data_alteracao: date | None = None
        if raw_alt := entry.get("data_alteracao"):
            with contextlib.suppress(ValueError, TypeError):
                data_alteracao = date.fromisoformat(raw_alt)

        return FonteJurisprudencia(
            id=source_id,
            tribunal=tribunal,
            tipo=tipo,
            numero=str(numero),
            ementa=texto,
            texto_integral=entry.get("texto_integral"),
            temas=entry.get("temas", [entry.get("tema", "")]) if entry.get("tema") or entry.get("temas") else [],
            base_legal=entry.get("base_legal", []),
            situacao=entry.get("situacao", "vigente"),
            hierarquia=hierarquia,
            data_aprovacao=data_aprovacao,
            data_alteracao=data_alteracao,
        )
