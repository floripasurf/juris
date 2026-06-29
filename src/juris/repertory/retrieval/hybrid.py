"""Hybrid retrieval combining dense and sparse search with hierarchy boosting.

Uses Reciprocal Rank Fusion (RRF) to merge results from dense (vector)
and sparse (FTS) retrieval, then boosts by jurisprudence hierarchy.
"""

from __future__ import annotations

from collections import defaultdict

from juris.repertory.corpus.models import HIERARCHY_WEIGHTS
from juris.repertory.embeddings import LegalEmbedder
from juris.repertory.retrieval.reranker import CrossEncoderReranker
from juris.repertory.vector_store import LocalFTSStore, SearchResult, VectorStore


class HybridRetriever:
    """Combines dense and sparse retrieval with hierarchy boosting.

    Args:
        dense_store: Vector store for dense (embedding) search.
        sparse_store: Vector store for sparse (FTS) search.
        embedder: Embedding model for query encoding.
    """

    def __init__(
        self,
        dense_store: VectorStore,
        sparse_store: VectorStore,
        embedder: LegalEmbedder,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self._dense = dense_store
        self._sparse = sparse_store
        self._embedder = embedder
        self._reranker = reranker

    def search(
        self, query: str, top_k: int = 10, *, apply_hierarchy_boost: bool = True
    ) -> list[SearchResult]:
        """Hybrid search combining dense and sparse results.

        Args:
            query: Search query text.
            top_k: Maximum number of results to return.
            apply_hierarchy_boost: Boost by authority level. Disable when a
                downstream composite re-rank (ADR-0017) already accounts for
                authority, to avoid double-counting it.

        Returns:
            Ranked list of search results.
        """
        # Dense retrieval
        dense_results: list[SearchResult] = []
        query_embedding = self._embedder.embed_single(query)
        if query_embedding is not None:
            dense_results = self._dense.search(query_embedding, top_k=top_k * 2)

        # Sparse retrieval
        sparse_results: list[SearchResult] = []
        if isinstance(self._sparse, LocalFTSStore):
            sparse_results = self._sparse.search_text(query, top_k=top_k * 2)
        else:
            # For non-FTS stores, try embedding search as fallback
            if query_embedding is not None:
                sparse_results = self._sparse.search(query_embedding, top_k=top_k * 2)

        # Merge via RRF
        merged = self.reciprocal_rank_fusion(dense_results, sparse_results)

        # Optional cross-encoder reranking
        if self._reranker is not None:
            merged = self._reranker.rerank(query, merged, top_k=min(15, top_k * 2))

        # Apply hierarchy boost (unless a composite re-rank handles authority).
        if apply_hierarchy_boost:
            merged = self.hierarchy_boost(merged, HIERARCHY_WEIGHTS)

        return merged[:top_k]

    @staticmethod
    def reciprocal_rank_fusion(
        dense: list[SearchResult],
        sparse: list[SearchResult],
        k: int = 60,
    ) -> list[SearchResult]:
        """Merge two ranked lists using Reciprocal Rank Fusion.

        Args:
            dense: Results from dense retrieval.
            sparse: Results from sparse retrieval.
            k: RRF constant (default 60).

        Returns:
            Merged and re-ranked results.
        """
        scores: dict[str, float] = defaultdict(float)
        result_map: dict[str, SearchResult] = {}

        for rank, result in enumerate(dense):
            scores[result.chunk_id] += 1.0 / (k + rank + 1)
            result_map[result.chunk_id] = result

        for rank, result in enumerate(sparse):
            scores[result.chunk_id] += 1.0 / (k + rank + 1)
            if result.chunk_id not in result_map:
                result_map[result.chunk_id] = result

        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        merged: list[SearchResult] = []
        for chunk_id in sorted_ids:
            original = result_map[chunk_id]
            merged.append(
                SearchResult(
                    chunk_id=original.chunk_id,
                    source_id=original.source_id,
                    score=scores[chunk_id],
                    text=original.text,
                    metadata=original.metadata,
                )
            )
        return merged

    @staticmethod
    def hierarchy_boost(
        results: list[SearchResult],
        weights: dict[int, float],
    ) -> list[SearchResult]:
        """Boost results by jurisprudence hierarchy weight.

        A Súmula Vinculante (hierarquia=1, weight=3.0) at rank 10 should
        outrank a precedente local (hierarquia=6, weight=1.0) at rank 2.

        Args:
            results: Search results to boost.
            weights: Mapping of hierarchy level to weight multiplier.

        Returns:
            Re-ranked results with hierarchy boosting applied.
        """
        boosted: list[SearchResult] = []
        for result in results:
            hierarquia = result.metadata.get("hierarquia", 6)
            weight = weights.get(hierarquia, 1.0)
            new_score = result.score * weight
            boosted.append(
                SearchResult(
                    chunk_id=result.chunk_id,
                    source_id=result.source_id,
                    score=new_score,
                    text=result.text,
                    metadata=result.metadata,
                )
            )
        boosted.sort(key=lambda r: r.score, reverse=True)
        return boosted
