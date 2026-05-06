"""Repertory service — public API for jurisprudence search.

Provides a high-level interface for searching the jurisprudence corpus
with optional filtering by tema, tribunal, and hierarchy level.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from juris.repertory.corpus.models import _HIERARCHY_LABELS
from juris.repertory.retrieval.hybrid import HybridRetriever
from juris.repertory.vector_store import SearchResult

if TYPE_CHECKING:
    from juris.llm.base import AbstractLLM
    from juris.persistence.audit import AuditLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """A processed search result with hierarchy information.

    Args:
        source_id: ID of the source document.
        score: Relevance score (higher is better).
        hierarchy: Hierarchy level (1-6).
        hierarchy_label: Human-readable hierarchy label.
        tribunal: Court identifier.
        texto: Matched text.
        base_legal: Referenced legal provisions.
    """

    source_id: str
    score: float
    hierarchy: int
    hierarchy_label: str
    tribunal: str
    texto: str
    base_legal: list[str] = field(default_factory=list)


class RepertoryService:
    """High-level service for searching the jurisprudence repertory.

    Args:
        retriever: Hybrid retriever instance.
    """

    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever
        self._hyde_cache: dict[str, str] = {}

    def search_jurisprudencia(
        self,
        query: str,
        temas: list[str] | None = None,
        tribunal: str | None = None,
        hierarquia_min: int | None = None,
        top_k: int = 10,
        use_hyde: bool = False,
        llm: AbstractLLM | None = None,
        audit: AuditLog | None = None,
    ) -> list[RetrievalResult]:
        """Search the jurisprudence corpus with optional filters.

        Args:
            query: Search query text.
            temas: Filter by subject tags.
            tribunal: Filter by court identifier.
            hierarquia_min: Minimum hierarchy level (1=most authoritative).
            top_k: Maximum number of results.
            use_hyde: Enable HyDE expansion for better recall.
            llm: LLM backend for HyDE generation.
            audit: Audit log for recording HyDE events.

        Returns:
            Ranked list of retrieval results.
        """
        # HyDE expansion: generate hypothetical document for better recall
        hyde_query: str | None = None
        if use_hyde and llm is not None:
            hyde_query = self._hyde_expand(query, llm, audit)

        # Get more results than needed for post-filtering
        fetch_k = top_k * 3 if (temas or tribunal or hierarquia_min) else top_k
        raw_results = self._retriever.search(query, top_k=fetch_k)

        # Merge HyDE results if available
        if hyde_query:
            hyde_results = self._retriever.search(hyde_query, top_k=fetch_k)
            seen: dict[str, SearchResult] = {}
            for r in raw_results + hyde_results:
                if r.source_id not in seen or r.score > seen[r.source_id].score:
                    seen[r.source_id] = r
            raw_results = sorted(seen.values(), key=lambda x: x.score, reverse=True)

        # Post-filter
        filtered = self._apply_filters(raw_results, temas, tribunal, hierarquia_min)

        # Convert to RetrievalResult
        output: list[RetrievalResult] = []
        for result in filtered[:top_k]:
            hierarquia = result.metadata.get("hierarquia", 6)
            output.append(
                RetrievalResult(
                    source_id=result.source_id,
                    score=result.score,
                    hierarchy=hierarquia,
                    hierarchy_label=_HIERARCHY_LABELS.get(
                        hierarquia, f"Nivel {hierarquia}"
                    ),
                    tribunal=result.metadata.get("tribunal", ""),
                    texto=result.text,
                    base_legal=result.metadata.get("base_legal", []),
                )
            )
        return output

    def _hyde_expand(
        self,
        query: str,
        llm: AbstractLLM,
        audit: AuditLog | None = None,
    ) -> str | None:
        """Generate hypothetical document for HyDE expansion."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]

        if query_hash in self._hyde_cache:
            return self._hyde_cache[query_hash]

        try:
            import asyncio

            from juris.prompts.hyde_v1 import EXPAND_PROMPT, SYSTEM_PROMPT

            prompt = EXPAND_PROMPT.format(query=query)

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    response = pool.submit(
                        asyncio.run,
                        llm.complete(
                            prompt=prompt,
                            system=SYSTEM_PROMPT,
                            temperature=0.25,
                            max_tokens=256,
                        ),
                    ).result()
            else:
                response = asyncio.run(
                    llm.complete(
                        prompt=prompt,
                        system=SYSTEM_PROMPT,
                        temperature=0.25,
                        max_tokens=256,
                    )
                )

            hypothetical = response.content.strip()
            if hypothetical:
                self._hyde_cache[query_hash] = hypothetical
                if audit:
                    audit.log(
                        event_type="retrieval.hyde",
                        actor=f"llm:{llm.model_name}",
                        details={
                            "query": query,
                            "hypothetical_length": len(hypothetical),
                        },
                    )
                return hypothetical
        except Exception:
            logger.warning("hyde_expansion_failed", exc_info=True)

        return None

    def find_template(
        self,
        tipo_peticao: str,
        area_direito: str | None = None,
    ) -> RetrievalResult | None:
        """Search for a matching petition template in the corpus.

        Args:
            tipo_peticao: Type of petition (e.g., "contestacao").
            area_direito: Area of law (e.g., "civil").

        Returns:
            Best matching template, or None.
        """
        query = f"modelo petição {tipo_peticao}"
        if area_direito:
            query += f" {area_direito}"

        results = self.search_jurisprudencia(
            query=query,
            top_k=5,
        )

        # Filter to MODELO_PETICAO only
        templates = [r for r in results if r.source_id.startswith("modelo_peticao_")]
        return templates[0] if templates else None

    @staticmethod
    def _apply_filters(
        results: list[SearchResult],
        temas: list[str] | None,
        tribunal: str | None,
        hierarquia_min: int | None,
    ) -> list[SearchResult]:
        """Apply post-retrieval filters.

        Args:
            results: Raw search results.
            temas: Filter by subject tags (any match).
            tribunal: Filter by court.
            hierarquia_min: Minimum hierarchy level.

        Returns:
            Filtered results.
        """
        filtered: list[SearchResult] = []
        for result in results:
            meta = result.metadata

            if tribunal and meta.get("tribunal", "").upper() != tribunal.upper():
                continue

            if hierarquia_min is not None:
                h = meta.get("hierarquia", 6)
                if h > hierarquia_min:
                    continue

            if temas:
                result_temas = meta.get("temas", [])
                if not any(t.lower() in [rt.lower() for rt in result_temas] for t in temas):
                    continue

            filtered.append(result)
        return filtered
