"""Cross-encoder reranker for improving retrieval precision."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from juris.repertory.vector_store import SearchResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RerankerScore:
    """Score from cross-encoder reranking."""

    chunk_id: str
    score: float
    cached: bool


class CrossEncoderReranker:
    """Reranks search results using a cross-encoder model.

    Lazy-loads the model on first use. Falls back gracefully
    if the model is unavailable.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cpu",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._model: object | None = None
        self._loaded = False
        self._cache: dict[str, float] = {}

    def _load_model(self) -> None:
        """Lazy-load the cross-encoder model."""
        if self._loaded:
            return
        self._loaded = True
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name, device=self._device)
            logger.info(
                "Loaded reranker model %s on %s", self._model_name, self._device
            )
        except Exception:
            logger.warning(
                "Could not load reranker model '%s'. Reranking will be skipped.",
                self._model_name,
            )
            self._model = None

    def _cache_key(self, query: str, source_id: str) -> str:
        """Generate cache key from query + source_id."""
        raw = f"{query}|{source_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int = 15,
    ) -> list[SearchResult]:
        """Rerank candidates using cross-encoder scores.

        Falls back to returning candidates unchanged if model unavailable.
        """
        self._load_model()
        if self._model is None or not candidates:
            return candidates[:top_k]

        scores: list[RerankerScore] = []
        uncached_pairs: list[tuple[int, str, str]] = []

        for i, result in enumerate(candidates):
            key = self._cache_key(query, result.source_id)
            if key in self._cache:
                scores.append(
                    RerankerScore(
                        chunk_id=result.chunk_id,
                        score=self._cache[key],
                        cached=True,
                    )
                )
            else:
                uncached_pairs.append((i, key, result.text))
                scores.append(
                    RerankerScore(
                        chunk_id=result.chunk_id,
                        score=0.0,  # placeholder
                        cached=False,
                    )
                )

        # Score uncached pairs
        if uncached_pairs:
            pairs = [[query, text] for _, _, text in uncached_pairs]
            try:
                raw_scores = self._model.predict(pairs)  # type: ignore[union-attr]
                for (idx, key, _), raw_score in zip(
                    uncached_pairs, raw_scores, strict=True
                ):
                    score_val = float(raw_score)
                    self._cache[key] = score_val
                    scores[idx] = RerankerScore(
                        chunk_id=candidates[idx].chunk_id,
                        score=score_val,
                        cached=False,
                    )
            except Exception:
                logger.warning("Reranking failed, returning original order")
                return candidates[:top_k]

        # Sort by score descending, rebuild SearchResult list
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1].score, reverse=True)

        reranked: list[SearchResult] = []
        for orig_idx, sc in indexed[:top_k]:
            orig = candidates[orig_idx]
            reranked.append(
                SearchResult(
                    chunk_id=orig.chunk_id,
                    source_id=orig.source_id,
                    score=sc.score,
                    text=orig.text,
                    metadata=orig.metadata,
                )
            )
        return reranked
