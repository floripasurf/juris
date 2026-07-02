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
# tenant_id=None is FAIL-SAFE: it returns only the shared public seed (tenant_id IS NULL),
# never another tenant's private uploads — so a caller that forgets to pass a tenant can
# never leak across firms (adversarial finding). Pass an explicit tenant_id for that firm.
_SEARCH_SQL = """
            SELECT c.chunk_id, c.source_id, c.text, c.metadata,
                   rank * -1 AS score
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id IS NULL
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

_QDRANT_PUBLIC_TENANT = "__juris_public__"


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
    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]], tenant_id: str | None = None) -> int:
        """Insert or update chunks with their embeddings.

        Args:
            chunks: Document chunks to store.
            embeddings: Corresponding embedding vectors.
            tenant_id: Tenant that owns private uploaded corpus chunks. ``None``
                means shared public seed only.

        Returns:
            Number of chunks upserted.
        """

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 10, tenant_id: str | None = None) -> list[SearchResult]:
        """Search for similar chunks.

        Args:
            query_embedding: Query vector.
            top_k: Maximum number of results.
            tenant_id: Restrict results to public seed plus this tenant's own
                private corpus. ``None`` returns public seed only.

        Returns:
            Ranked list of search results.
        """

    @abstractmethod
    def delete(self, source_id: str, tenant_id: str | None = None) -> int:
        """Delete all chunks from a given source.

        Args:
            source_id: ID of the source to delete.
            tenant_id: Tenant scope for the deletion. ``None`` deletes only the
                shared public seed's copy of this source.

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

    @staticmethod
    def _tenant_payload_value(tenant_id: str | None) -> str:
        """Tenant marker stored in Qdrant payloads.

        Qdrant filters match strict scalar values. Use an explicit public marker
        instead of missing/null fields so legacy unscoped points fail closed until
        they are reingested with tenant metadata.
        """
        return tenant_id if tenant_id is not None else _QDRANT_PUBLIC_TENANT

    @classmethod
    def _tenant_match(cls, tenant_id: str | None) -> Any:
        from qdrant_client.models import FieldCondition, MatchValue

        return FieldCondition(
            key="tenant_id",
            match=MatchValue(value=cls._tenant_payload_value(tenant_id)),
        )

    @classmethod
    def _visibility_filter(cls, tenant_id: str | None) -> Any:
        from qdrant_client.models import Filter

        public_match = cls._tenant_match(None)
        if tenant_id is None:
            return Filter(must=[public_match])
        return Filter(should=[public_match, cls._tenant_match(tenant_id)])

    @classmethod
    def _delete_filter(cls, source_id: str, tenant_id: str | None) -> Any:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        return Filter(
            must=[
                FieldCondition(key="source_id", match=MatchValue(value=source_id)),
                cls._tenant_match(tenant_id),
            ]
        )

    @staticmethod
    def _hits_from_qdrant_response(response: Any) -> list[Any]:
        points = getattr(response, "points", None)
        if points is not None:
            return list(points)
        return list(response or [])

    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]], tenant_id: str | None = None) -> int:
        """Upsert chunks into Qdrant."""
        from qdrant_client.models import PointStruct

        client = self._get_client()
        points = []
        tenant_payload = self._tenant_payload_value(tenant_id)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            points.append(
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id)),
                    vector=embedding,
                    payload={
                        **chunk.metadata,
                        "chunk_id": chunk.chunk_id,
                        "source_id": chunk.source_id,
                        "source_type": chunk.source_type.value,
                        "text": chunk.text,
                        "position": chunk.position,
                        "tenant_id": tenant_payload,
                    },
                )
            )
        client.upsert(collection_name=self._collection, points=points)
        return len(points)

    def search(self, query_embedding: list[float], top_k: int = 10, tenant_id: str | None = None) -> list[SearchResult]:
        """Search Qdrant for similar chunks."""
        client = self._get_client()
        query_filter = self._visibility_filter(tenant_id)
        if hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=self._collection,
                query=query_embedding,
                query_filter=query_filter,
                limit=top_k,
            )
        else:
            response = client.search(
                collection_name=self._collection,
                query_vector=query_embedding,
                query_filter=query_filter,
                limit=top_k,
            )
        hits = self._hits_from_qdrant_response(response)
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
                        k: v for k, v in payload.items() if k not in ("chunk_id", "source_id", "tenant_id", "text")
                    },
                )
            )
        return results

    def delete(self, source_id: str, tenant_id: str | None = None) -> int:
        """Delete all chunks for a source from Qdrant."""
        client = self._get_client()
        result = client.delete(
            collection_name=self._collection,
            points_selector=self._delete_filter(source_id, tenant_id),
        )
        logger.info("Deleted chunks for source_id=%s tenant_scoped=%s from Qdrant", source_id, tenant_id is not None)
        return 0 if result is None else 1


class LocalFTSStore(VectorStore):
    """SQLite FTS5 fallback for offline/dev mode.

    Args:
        db_path: Path to SQLite database file. Uses in-memory if None.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else ":memory:"
        # check_same_thread=False so a cached store (e.g. the /api/corpus/search service)
        # can be read from FastAPI's threadpool without sqlite3.ProgrammingError. Safe
        # because sqlite3.threadsafety==3 (serialized): SQLite locks access internally.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
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

    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]], tenant_id: str | None = None) -> int:
        """Insert chunks into SQLite FTS (embeddings ignored for FTS).

        ``tenant_id`` scopes tenant-uploaded corpus (tier-2 doutrina / tier-3 petition
        history) to one firm; leave it ``None`` for the shared public seed (tier-1).
        """
        count = 0
        for chunk in chunks:
            # Delete existing if any
            existing = self._conn.execute("SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)).fetchone()
            if existing:
                self._conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (existing[0],))
                self._conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,))

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
            rowid = self._conn.execute("SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)).fetchone()[0]
            self._conn.execute(
                "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                (rowid, chunk.text),
            )
            count += 1
        self._conn.commit()
        return count

    def search(self, query_embedding: list[float], top_k: int = 10, tenant_id: str | None = None) -> list[SearchResult]:
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

    def delete(self, source_id: str, tenant_id: str | None = None) -> int:
        """Delete all chunks for a source."""
        if tenant_id is None:
            rows = self._conn.execute(
                "SELECT rowid FROM chunks WHERE source_id = ? AND tenant_id IS NULL", (source_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT rowid FROM chunks WHERE source_id = ? AND tenant_id = ?", (source_id, tenant_id)
            ).fetchall()
        for (rowid,) in rows:
            self._conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (rowid,))
        if tenant_id is None:
            self._conn.execute("DELETE FROM chunks WHERE source_id = ? AND tenant_id IS NULL", (source_id,))
        else:
            self._conn.execute("DELETE FROM chunks WHERE source_id = ? AND tenant_id = ?", (source_id, tenant_id))
        self._conn.commit()
        return len(rows)

    def count_by_tenant(self, tenant_id: str) -> int:
        """Return the number of private corpus chunks for a tenant."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()
        return int(row[0] if row else 0)

    def delete_by_tenant(self, tenant_id: str) -> int:
        """Delete all private corpus chunks for a tenant.

        Public seed chunks keep ``tenant_id IS NULL`` and are intentionally not
        touched. The FTS shadow table is cleaned first so deleted private text
        cannot remain searchable.
        """
        rows = self._conn.execute(
            "SELECT rowid FROM chunks WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        for (rowid,) in rows:
            self._conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (rowid,))
        self._conn.execute("DELETE FROM chunks WHERE tenant_id = ?", (tenant_id,))
        self._conn.commit()
        return len(rows)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
