"""Vector store abstraction with Qdrant and SQLite FTS5 implementations.

Provides a unified interface for upserting, searching, and deleting
document chunks with their embeddings.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import uuid
from abc import ABC, abstractmethod
from array import array
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import ESTILO_SOURCE_TYPES, normalize_area, resolve_uso

logger = logging.getLogger(__name__)

# Deterministic derivation for chunks stored before the `uso` column existed (or with
# no explicit uso): explicit chunk.uso wins; otherwise fall back to the tipo's default
# via source_type. Built from the internal enum's values at import time — safe, never
# user input — so it can be embedded directly in the module-constant SQL below.
_ESTILO_IN = ", ".join(f"'{t}'" for t in sorted(ESTILO_SOURCE_TYPES))
_USO_EFETIVO = (
    "COALESCE(NULLIF(c.uso, ''), CASE WHEN c.source_type IN (" + _ESTILO_IN + ") "
    "THEN 'estilo' ELSE 'fundamento' END)"
)
_ESTILO_FILTER = f"AND {_USO_EFETIVO} = 'fundamento'"
_AREA_EFETIVA = "LOWER(COALESCE(json_extract(c.metadata, '$.area'), ''))"
_AREA_MATCH = f"({_AREA_EFETIVA} = ? OR {_AREA_EFETIVA} = 'geral')"
_SELECT_COLUMNS = f"""
            SELECT c.chunk_id, c.source_id, c.text, c.metadata,
                   c.source_type, {_USO_EFETIVO} AS uso_efetivo,
                   rank * -1 AS score"""
_DENSE_SELECT_COLUMNS = f"""
            SELECT c.chunk_id, c.source_id, c.text, c.metadata,
                   c.source_type, {_USO_EFETIVO} AS uso_efetivo,
                   c.embedding
            FROM chunks c"""  # noqa: S608 - built only from module constants, never user input

# Fixed FTS5 search statements. Kept as module constants (not built at call time) so
# the tenant filter can never be confused with an interpolation point: the tenant value
# is always a bound parameter (?), never string-formatted into the SQL. Three combinable
# axes — tenant scope (public / public+tenant / tenant-only) × uso filter (fundamento-only
# default / include_estilo) — give the six variants below.
# tenant_id=None is FAIL-SAFE: it returns only the shared public seed (tenant_id IS NULL),
# never another tenant's private uploads — so a caller that forgets to pass a tenant can
# never leak across firms (adversarial finding). Pass an explicit tenant_id for that firm.
# The uso filter is applied in the WHERE clause, before the top_k cut (L2 requirement) —
# never as a post-filter on already-truncated results.
_SEARCH_SQL = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id IS NULL
                {_ESTILO_FILTER}
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_ESTILO = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id IS NULL
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND (c.tenant_id IS NULL OR c.tenant_id = ?)
                {_ESTILO_FILTER}
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_ESTILO = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND (c.tenant_id IS NULL OR c.tenant_id = ?)
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_AREA = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND (c.tenant_id IS NULL OR (c.tenant_id = ? AND {_AREA_MATCH}))
                {_ESTILO_FILTER}
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_AREA_ESTILO = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND (c.tenant_id IS NULL OR (c.tenant_id = ? AND {_AREA_MATCH}))
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_ONLY = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id = ?
                {_ESTILO_FILTER}
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_ONLY_ESTILO = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id = ?
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_ONLY_AREA = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id = ? AND {_AREA_MATCH}
                {_ESTILO_FILTER}
            ORDER BY rank
            LIMIT ?
            """
_SEARCH_SQL_TENANT_ONLY_AREA_ESTILO = f"""{_SELECT_COLUMNS}
            FROM chunks_fts f
            JOIN chunks c ON c.rowid = f.rowid
            WHERE chunks_fts MATCH ? AND c.tenant_id = ? AND {_AREA_MATCH}
            ORDER BY rank
            LIMIT ?
            """

_QDRANT_PUBLIC_TENANT = "__juris_public__"


def _metadata_for_storage(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return persisted metadata with canonical practice-area labels."""
    stored = dict(metadata)
    area = normalize_area(str(stored.get("area") or ""))
    if area:
        stored["area"] = area
    return stored


def _embedding_to_blob(embedding: list[float]) -> bytes | None:
    """Serialize a dense vector as compact float32 bytes for SQLite storage."""
    if not embedding:
        return None
    return array("f", (float(value) for value in embedding)).tobytes()


def _embedding_from_blob(blob: bytes) -> list[float]:
    """Deserialize a dense vector stored by ``_embedding_to_blob``."""
    values = array("f")
    values.frombytes(blob)
    return list(values)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single search result from the vector store.

    Args:
        chunk_id: ID of the matched chunk.
        source_id: ID of the parent source.
        score: Relevance score (higher is better).
        text: Text content of the matched chunk.
        metadata: Additional metadata from the chunk.
        source_type: Type of the parent source (e.g. ``"acordao_publicado"``).
        uso: Effective uso — ``"fundamento"`` or ``"estilo"`` — explicit or derived.
    """

    chunk_id: str
    source_id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = ""
    uso: str = ""


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
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        tenant_id: str | None = None,
        *,
        include_estilo: bool = False,
        tenant_only: bool = False,
        area: str | None = None,
    ) -> list[SearchResult]:
        """Search for similar chunks.

        Args:
            query_embedding: Query vector.
            top_k: Maximum number of results.
            tenant_id: Restrict results to public seed plus this tenant's own
                private corpus. ``None`` returns public seed only.
            include_estilo: If ``False`` (default), exclude ``uso="estilo"``
                chunks (e.g. modelos de petição) from grounding results.
            tenant_only: If ``True``, exclude the shared public seed and
                return only this tenant's own points.

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
    """Qdrant-based vector store adapter for the deferred scale-out path.

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
    def _area_match(cls, area: str) -> Any:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        return Filter(
            should=[
                FieldCondition(key="area", match=MatchValue(value=area)),
                FieldCondition(key="area", match=MatchValue(value="geral")),
            ]
        )

    @classmethod
    def _search_filter(
        cls,
        tenant_id: str | None,
        *,
        include_estilo: bool,
        tenant_only: bool,
        area: str | None = None,
    ) -> Any:
        """Build the ``Filter`` for ``search()``, combining tenant scope and the uso axis.

        Starts from the existing tenant visibility filter (or, when ``tenant_only``
        is set, a filter restricted to just this tenant's own points, excluding the
        shared public seed) and, unless ``include_estilo`` is ``True``, adds a
        ``must_not`` on ``uso == "estilo"`` so estilo-only sources (modelos de
        petição etc.) never leak into grounding results — mirroring
        ``LocalFTSStore.search_text``'s ``include_estilo`` behavior (L2).

        Operational note on legacy points: Qdrant's ``must_not`` on a field match
        only excludes points where that field is present and equals the given
        value — it does NOT exclude points where the field is simply absent from
        the payload. Points upserted before this task's payload change have no
        ``uso`` key at all and are therefore NOT excluded by this filter. This is
        acceptable because those legacy points are still scoped by ``tenant_id``
        (fail-closed) and will start being excluded once reingested through the
        updated ``upsert()``, which always writes ``uso``.

        Args:
            tenant_id: Tenant to scope to; ``None`` means public-seed only.
            include_estilo: If ``False`` (default), exclude ``uso="estilo"`` points.
            tenant_only: If ``True``, restrict to this tenant's own points only,
                excluding the shared public seed. Meaningful only with a
                non-``None`` ``tenant_id``.

        Returns:
            A ``qdrant_client.models.Filter`` ready to pass as ``query_filter``.
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        normalized_area = normalize_area(area)
        if normalized_area and tenant_id is not None:
            private_area = Filter(must=[cls._tenant_match(tenant_id), cls._area_match(normalized_area)])
            base = private_area if tenant_only else Filter(should=[cls._tenant_match(None), private_area])
        else:
            base = Filter(must=[cls._tenant_match(tenant_id)]) if tenant_only else cls._visibility_filter(tenant_id)
        if include_estilo:
            return base
        return Filter(
            must=base.must,
            should=base.should,
            must_not=[FieldCondition(key="uso", match=MatchValue(value="estilo"))],
        )

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
        """Upsert chunks into Qdrant.

        Payload gets ``uso`` (explicit ``chunk.uso``, else derived from
        ``source_type`` via ``resolve_uso`` — same fallback as ``LocalFTSStore``)
        and ``source_type`` so ``search()`` can filter on the uso axis (L2).
        """
        from qdrant_client.models import PointStruct

        client = self._get_client()
        points = []
        tenant_payload = self._tenant_payload_value(tenant_id)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            uso_val = chunk.uso or resolve_uso(chunk.source_type).value
            metadata = _metadata_for_storage(chunk.metadata)
            points.append(
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id)),
                    vector=embedding,
                    payload={
                        **metadata,
                        "chunk_id": chunk.chunk_id,
                        "source_id": chunk.source_id,
                        "source_type": chunk.source_type.value,
                        "uso": uso_val,
                        "text": chunk.text,
                        "position": chunk.position,
                        "tenant_id": tenant_payload,
                    },
                )
            )
        client.upsert(collection_name=self._collection, points=points)
        return len(points)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        tenant_id: str | None = None,
        *,
        include_estilo: bool = False,
        tenant_only: bool = False,
        area: str | None = None,
    ) -> list[SearchResult]:
        """Search Qdrant for similar chunks.

        Args:
            query_embedding: Query vector.
            top_k: Maximum number of results.
            tenant_id: Restrict results to public seed plus this tenant's own
                private corpus. ``None`` returns public seed only.
            include_estilo: If ``False`` (default), points with ``uso="estilo"``
                are excluded — see ``_search_filter`` for the legacy-points caveat.
            tenant_only: If ``True``, exclude the shared public seed and return
                only this tenant's own points.

        Returns:
            Ranked list of search results.
        """
        client = self._get_client()
        query_filter = self._search_filter(
            tenant_id, include_estilo=include_estilo, tenant_only=tenant_only, area=area
        )
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
                        k: v
                        for k, v in payload.items()
                        if k not in ("chunk_id", "source_id", "tenant_id", "text", "source_type", "uso")
                    },
                    source_type=payload.get("source_type", ""),
                    uso=payload.get("uso", ""),
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
    """SQLite FTS5 store used by the current pilot runtime.

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
                tenant_id TEXT,
                embedding BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
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
        if "embedding" not in cols:
            self._conn.execute("ALTER TABLE chunks ADD COLUMN embedding BLOB")
        with contextlib.suppress(sqlite3.OperationalError):  # coluna já existe
            self._conn.execute("ALTER TABLE chunks ADD COLUMN uso TEXT")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id)")
        self._conn.commit()

    def upsert(self, chunks: list[DocumentChunk], embeddings: list[list[float]], tenant_id: str | None = None) -> int:
        """Insert chunks into SQLite FTS and persist dense embeddings.

        ``tenant_id`` scopes tenant-uploaded corpus (tier-2 doutrina / tier-3 petition
        history) to one firm; leave it ``None`` for the shared public seed (tier-1).
        """
        count = 0
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            # Delete existing if any
            existing = self._conn.execute("SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)).fetchone()
            if existing:
                self._conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (existing[0],))
                self._conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,))

            uso_val = chunk.uso or resolve_uso(chunk.source_type).value
            metadata = _metadata_for_storage(chunk.metadata)
            embedding_blob = _embedding_to_blob(embedding)
            self._conn.execute(
                "INSERT INTO chunks "
                "(chunk_id, source_id, source_type, text, metadata, position, tenant_id, uso, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.source_type.value,
                    chunk.text,
                    json.dumps(metadata, ensure_ascii=False),
                    chunk.position,
                    tenant_id,
                    uso_val,
                    embedding_blob,
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

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        tenant_id: str | None = None,
        *,
        include_estilo: bool = False,
        tenant_only: bool = False,
        area: str | None = None,
    ) -> list[SearchResult]:
        """Search using persisted dense embeddings.

        The pilot stores normalized BGE vectors as float32 blobs in SQLite. For
        normalized vectors, cosine similarity is the dot product.
        """
        if top_k <= 0 or not query_embedding:
            return []

        query = [float(value) for value in query_embedding]
        normalized_area = normalize_area(area)
        where = ["c.embedding IS NOT NULL"]
        params: list[object] = []

        if tenant_id is None:
            where.append("c.tenant_id IS NULL")
        elif tenant_only and normalized_area:
            where.append(f"c.tenant_id = ? AND {_AREA_MATCH}")
            params.extend([tenant_id, normalized_area])
        elif tenant_only:
            where.append("c.tenant_id = ?")
            params.append(tenant_id)
        elif normalized_area:
            where.append(f"(c.tenant_id IS NULL OR (c.tenant_id = ? AND {_AREA_MATCH}))")
            params.extend([tenant_id, normalized_area])
        else:
            where.append("(c.tenant_id IS NULL OR c.tenant_id = ?)")
            params.append(tenant_id)
        if not include_estilo:
            where.append(f"{_USO_EFETIVO} = 'fundamento'")

        sql = f"{_DENSE_SELECT_COLUMNS} WHERE {' AND '.join(where)} ORDER BY c.chunk_id"
        rows = self._conn.execute(sql, tuple(params)).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            vector = _embedding_from_blob(row[6])
            if len(vector) != len(query):
                continue
            score = sum(left * right for left, right in zip(query, vector, strict=True))
            meta = json.loads(row[3]) if row[3] else {}
            results.append(
                SearchResult(
                    chunk_id=row[0],
                    source_id=row[1],
                    score=float(score),
                    text=row[2],
                    metadata=meta,
                    source_type=row[4] or "",
                    uso=row[5] or "",
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:top_k]

    def search_text(
        self,
        query: str,
        top_k: int = 10,
        tenant_id: str | None = None,
        *,
        include_estilo: bool = False,
        tenant_only: bool = False,
        area: str | None = None,
    ) -> list[SearchResult]:
        """Full-text search using FTS5.

        Args:
            query: Search query text.
            top_k: Maximum number of results.
            tenant_id: If given, restrict to the shared public seed (tenant_id IS NULL)
                plus THIS tenant's own uploads — never another firm's private corpus.
            include_estilo: If ``False`` (default), only ``uso="fundamento"`` chunks are
                returned — estilo-only sources (e.g. modelos de petição) never leak into
                grounding results. The filter runs in the WHERE clause, before top_k.
            tenant_only: If ``True`` (requires a ``tenant_id``), exclude the shared public
                seed and return only this tenant's own uploads.

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

        # Tenant scope × uso filter: all SQL statements are fixed module-level literals
        # (no interpolation) — the tenant value travels as a bound parameter, so there is
        # no injection surface despite the branching.
        normalized_area = normalize_area(area)
        if tenant_id is None:
            sql = _SEARCH_SQL_ESTILO if include_estilo else _SEARCH_SQL
            params: tuple[object, ...] = (safe_query, top_k)
        elif tenant_only and normalized_area:
            sql = _SEARCH_SQL_TENANT_ONLY_AREA_ESTILO if include_estilo else _SEARCH_SQL_TENANT_ONLY_AREA
            params = (safe_query, tenant_id, normalized_area, top_k)
        elif tenant_only:
            sql = _SEARCH_SQL_TENANT_ONLY_ESTILO if include_estilo else _SEARCH_SQL_TENANT_ONLY
            params = (safe_query, tenant_id, top_k)
        elif normalized_area:
            sql = _SEARCH_SQL_TENANT_AREA_ESTILO if include_estilo else _SEARCH_SQL_TENANT_AREA
            params = (safe_query, tenant_id, normalized_area, top_k)
        else:
            sql = _SEARCH_SQL_TENANT_ESTILO if include_estilo else _SEARCH_SQL_TENANT
            params = (safe_query, tenant_id, top_k)
        rows = self._conn.execute(sql, params).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            meta = json.loads(row[3]) if row[3] else {}
            results.append(
                SearchResult(
                    chunk_id=row[0],
                    source_id=row[1],
                    score=row[6],
                    text=row[2],
                    metadata=meta,
                    source_type=row[4] or "",
                    uso=row[5] or "",
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

    def missing_embedding_count(self) -> int:
        """Return the number of chunks that still need dense embeddings."""
        row = self._conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NULL").fetchone()
        return int(row[0] if row else 0)

    def fetch_chunks_missing_embeddings(self, *, limit: int = 100) -> list[tuple[str, str]]:
        """Return ``(chunk_id, text)`` pairs for dense-embedding backfill."""
        rows = self._conn.execute(
            """
            SELECT chunk_id, text
            FROM chunks
            WHERE embedding IS NULL
            ORDER BY chunk_id
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def update_embeddings(self, embeddings_by_chunk_id: Mapping[str, list[float]]) -> int:
        """Persist dense embeddings for existing chunks by id."""
        count = 0
        for chunk_id, embedding in embeddings_by_chunk_id.items():
            blob = _embedding_to_blob(embedding)
            if blob is None:
                continue
            cursor = self._conn.execute(
                "UPDATE chunks SET embedding = ? WHERE chunk_id = ?",
                (blob, chunk_id),
            )
            count += cursor.rowcount
        self._conn.commit()
        return count

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
