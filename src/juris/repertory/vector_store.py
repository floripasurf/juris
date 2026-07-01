"""Vector store abstraction with Qdrant and SQLite FTS5 implementations.

Provides a unified interface for upserting, searching, and deleting
document chunks with their embeddings.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from juris.repertory.chunking import DocumentChunk

logger = logging.getLogger(__name__)

# Fixed FTS5 search statements. Kept as module constants (not built at call time) so
# the tenant filter can never be confused with an interpolation point: the tenant value
# is always a bound parameter (?), never string-formatted into the SQL.
_SEARCH_SQL = """
            SELECT c.chunk_id, c.source_id, c.text, c.metadata,
                   rank * -1 AS score
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT = """
            SELECT c.chunk_id, c.source_id, c.text, c.metadata,
                   rank * -1 AS score
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND (c.tenant_id IS NULL OR c.tenant_id = ?)
            ORDER BY rank
            LIMIT ?
            """


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single search result from the vector store.

    Args:
        chunk_id: ID of the matched chunk.
        source_id: ID of the parent source.
        score: Relevance score (higher is better).
        text: Text content of the matched chunk.
        metadata: Additional metadata from the chunk.
    """

    chunk_id: str
    source_id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Abstract base class for vector stores."""

    @abstractmethod
    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> int:
        """Insert or update chunks with their embeddings.

        Args:
            chunks: Document chunks to store.
            embeddings: Corresponding embedding vectors.

        Returns:
            Number of chunks upserted.
        """

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchResult]:
        """Search for similar chunks.

        Args:
            query_embedding: Query vector.
            top_k: Maximum number of results.

        Returns:
            Ranked list of search results.
        """

    @abstractmethod
    def delete(self, source_id: str) -> int:
        """Delete all chunks from a given source.

        Args:
            source_id: ID of the source to delete.

        Returns:
            Number of chunks deleted.
        """


class QdrantVectorStore(VectorStore):
    """Qdrant-based vector store for production use.

    Args:
        url: Qdrant server URL.
        collection: Name of the Qdrant collection.
        dimension: Embedding vector dimension.
    """

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "jurisprudencia",
        dimension: int = 1024,
    ) -> None:
        self._url = url
        self._collection = collection
        self._dimension = dimension
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazy-load Qdrant client and ensure collection exists."""
        if self._client is not None:
            return self._client
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._client = QdrantClient(url=self._url)
        collections = [c.name for c in self._client.get_collections().collections]
        if self._collection not in collections:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._dimension, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection '%s'", self._collection)
        return self._client

    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> int:
        """Upsert chunks into Qdrant."""
        from qdrant_client.models import PointStruct

        client = self._get_client()
        points = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            points.append(
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id)),
                    vector=embedding,
                    payload={
                        "chunk_id": chunk.chunk_id,
                        "source_id": chunk.source_id,
                        "source_type": chunk.source_type.value,
                        "text": chunk.text,
                        "position": chunk.position,
                        **chunk.metadata,
                    },
                )
            )
        client.upsert(collection_name=self._collection, points=points)
        return len(points)

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchResult]:
        """Search Qdrant for similar chunks."""
        client = self._get_client()
        hits = client.search(
            collection_name=self._collection,
            query_vector=query_embedding,
            limit=top_k,
        )
        results: list[SearchResult] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                SearchResult(
                    chunk_id=payload.get("chunk_id", ""),
                    source_id=payload.get("source_id", ""),
                    score=hit.score,
                    text=payload.get("text", ""),
                    metadata={
                        k: v
                        for k, v in payload.items()
                        if k not in ("chunk_id", "source_id", "text")
                    },
                )
            )
        return results

    def delete(self, source_id: str) -> int:
        """Delete all chunks for a source from Qdrant."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = self._get_client()
        result = client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
            ),
        )
        logger.info("Deleted chunks for source_id=%s from Qdrant", source_id)
        return 0 if result is None else 1


class LocalFTSStore(VectorStore):
    """SQLite FTS5 fallback for offline/dev mode.

    Args:
        db_path: Path to SQLite database file. Uses in-memory if None.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else ":memory:"
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self) -> None:
        """Create FTS5 and metadata tables."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_type TEXT,
                text TEXT NOT NULL,
                metadata TEXT,
                position INTEGER DEFAULT 0,
                tenant_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                text,
                content=chunks,
                content_rowid=rowid
            );
        """)
        # Migrate DBs created before tenant scoping (tier-2/3 uploads must not leak
        # across firms; NULL tenant_id = shared public seed, visible to all).
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(chunks)")}
        if "tenant_id" not in cols:
            self._conn.execute("ALTER TABLE chunks ADD COLUMN tenant_id TEXT")
        self._conn.commit()

    def upsert(
        self, chunks: list[DocumentChunk], embeddings: list[list[float]], tenant_id: str | None = None
    ) -> int:
        """Insert chunks into SQLite FTS (embeddings ignored for FTS).

        ``tenant_id`` scopes tenant-uploaded corpus (tier-2 doutrina / tier-3 petition
        history) to one firm; leave it ``None`` for the shared public seed (tier-1).
        """
        count = 0
        for chunk in chunks:
            # Delete existing if any
            existing = self._conn.execute(
                "SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
            ).fetchone()
            if existing:
                self._conn.execute(
                    "DELETE FROM chunks_fts WHERE rowid = ?", (existing[0],)
                )
                self._conn.execute(
                    "DELETE FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
                )

            self._conn.execute(
                "INSERT INTO chunks (chunk_id, source_id, source_type, text, metadata, position, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.source_type.value,
                    chunk.text,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                    chunk.position,
                    tenant_id,
                ),
            )
            rowid = self._conn.execute(
                "SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
            ).fetchone()[0]
            self._conn.execute(
                "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                (rowid, chunk.text),
            )
            count += 1
        self._conn.commit()
        return count

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[SearchResult]:
        """Search using FTS5 (query_embedding is ignored; uses metadata for text query).

        For FTS-based search, use search_text() instead.
        This method returns an empty list since FTS cannot use embeddings.
        """
        return []

    def search_text(self, query: str, top_k: int = 10, tenant_id: str | None = None) -> list[SearchResult]:
        """Full-text search using FTS5.

        Args:
            query: Search query text.
            top_k: Maximum number of results.
            tenant_id: If given, restrict to the shared public seed (tenant_id IS NULL)
                plus THIS tenant's own uploads — never another firm's private corpus.

        Returns:
            Ranked list of search results.
        """
        # Sanitize query for FTS5 — use OR for better recall
        # Strip FTS5 special chars (dots, hyphens, colons, parens, etc.) and quote each token
        import re as _re

        raw_words = query.split()
        words: list[str] = []
        for w in raw_words:
            if w.upper() in ("NOT", "AND", "OR"):
                continue
            cleaned = _re.sub(r"[^\w]", " ", w).split()
            words.extend(c for c in cleaned if c)
        if not words:
            return []
        # Double-quote each token to avoid FTS5 syntax errors
        safe_query = " OR ".join(f'"{w}"' for w in words)

        # Tenant scope: public seed (NULL) + this tenant's own uploads only. Both SQL
        # statements are fixed literals (no interpolation) — the tenant value travels as
        # a bound parameter, so there is no injection surface despite the branch.
        if tenant_id is None:
            sql = _SEARCH_SQL
            params: tuple[object, ...] = (safe_query, top_k)
        else:
            sql = _SEARCH_SQL_TENANT
            params = (safe_query, tenant_id, top_k)
        rows = self._conn.execute(sql, params).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            meta = json.loads(row[3]) if row[3] else {}
            results.append(
                SearchResult(
                    chunk_id=row[0],
                    source_id=row[1],
                    score=row[4],
                    text=row[2],
                    metadata=meta,
                )
            )
        return results

    def delete(self, source_id: str) -> int:
        """Delete all chunks for a source."""
        rows = self._conn.execute(
            "SELECT rowid FROM chunks WHERE source_id = ?", (source_id,)
        ).fetchall()
        for (rowid,) in rows:
            self._conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (rowid,))
        self._conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        self._conn.commit()
        return len(rows)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
