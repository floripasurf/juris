"""Researcher agent — finds supporting and opposing jurisprudence for a thesis."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM
from juris.persistence.audit import AuditLog
from juris.repertory.corpus.models import _HIERARCHY_LABELS
from juris.repertory.retrieval.service import RepertoryService, RetrievalResult

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResearchQuery:
    """Query for the researcher agent."""

    thesis: str
    case_context: dict[str, Any] = field(default_factory=dict)
    desired_authority_min: int = 4
    top_k: int = 8


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Result from the researcher agent."""

    thesis: str
    supporting: list[RetrievalResult] = field(default_factory=list)
    opposing: list[RetrievalResult] = field(default_factory=list)
    coverage_note: str = ""
    has_strong_opposition: bool = False


class Researcher:
    """Finds supporting and opposing jurisprudence for a thesis.

    Uses HyDE-augmented search for supporting sources, and an antithesis
    loop for opposing sources.
    """

    def __init__(
        self,
        repertory: RepertoryService,
        llm: AbstractLLM,
        audit: AuditLog | None = None,
    ) -> None:
        self._repertory = repertory
        self._llm = llm
        self._audit = audit

    async def research(self, query: ResearchQuery) -> ResearchResult:
        """Research supporting and opposing jurisprudence for a thesis."""
        # 1. Supporting: HyDE-augmented search
        supporting = self._repertory.search_jurisprudencia(
            query=query.thesis,
            top_k=query.top_k,
            use_hyde=True,
            llm=self._llm,
            audit=self._audit,
        )

        # 2. Opposing: antithesis loop
        opposing = await self._find_opposing(query)

        # 3. Coverage note
        coverage_note = self._build_coverage_note(supporting, opposing)

        # 4. Strong opposition check
        has_strong = any(r.hierarchy <= 4 for r in opposing)

        # 5. Audit
        if self._audit:
            self._audit.log(
                event_type="research",
                actor=f"llm:{self._llm.model_name}",
                details={
                    "thesis": query.thesis,
                    "supporting_ids": [r.source_id for r in supporting],
                    "opposing_ids": [r.source_id for r in opposing],
                    "has_strong_opposition": has_strong,
                    "hyde_used": True,
                },
            )

        return ResearchResult(
            thesis=query.thesis,
            supporting=supporting,
            opposing=opposing,
            coverage_note=coverage_note,
            has_strong_opposition=has_strong,
        )

    async def _find_opposing(self, query: ResearchQuery) -> list[RetrievalResult]:
        """Generate antithesis phrasings and search for opposing jurisprudence."""
        try:
            antithesis_prompt = (
                f"Tese juridica: {query.thesis}\n\n"
                "Gere 3 formulacoes da tese CONTRARIA (antitese) em uma linha cada. "
                "Apenas as formulacoes, sem numeracao ou explicacoes."
            )
            response = await self._llm.complete(
                prompt=antithesis_prompt,
                temperature=0.3,
                max_tokens=256,
            )
            phrasings = [
                line.strip()
                for line in response.content.strip().split("\n")
                if line.strip() and len(line.strip()) > 10
            ][:3]
        except Exception:
            logger.warning("antithesis_generation_failed")
            phrasings = [f"improcedencia {query.thesis}"]

        # Search for each phrasing and dedupe
        seen_ids: set[str] = set()
        all_opposing: list[RetrievalResult] = []

        for phrasing in phrasings:
            results = self._repertory.search_jurisprudencia(
                query=phrasing,
                top_k=5,
            )
            for r in results:
                if r.source_id not in seen_ids:
                    seen_ids.add(r.source_id)
                    all_opposing.append(r)

        # Sort by hierarchy (most authoritative first) and take top 3
        all_opposing.sort(key=lambda r: (r.hierarchy, -r.score))
        return all_opposing[:3]

    @staticmethod
    def _build_coverage_note(
        supporting: list[RetrievalResult],
        opposing: list[RetrievalResult],
    ) -> str:
        """Build deterministic coverage note from metadata counts."""

        def count_by_hierarchy(results: list[RetrievalResult]) -> dict[str, int]:
            counts: dict[str, int] = {}
            for r in results:
                label = _HIERARCHY_LABELS.get(r.hierarchy, f"Nivel {r.hierarchy}")
                counts[label] = counts.get(label, 0) + 1
            return counts

        sup_counts = count_by_hierarchy(supporting)
        opp_counts = count_by_hierarchy(opposing)

        parts: list[str] = []
        if sup_counts:
            items = [f"{v} {k}" for k, v in sup_counts.items()]
            parts.append(f"Favoraveis: {', '.join(items)}")
        else:
            parts.append("Favoraveis: nenhuma encontrada")

        if opp_counts:
            items = [f"{v} {k}" for k, v in opp_counts.items()]
            parts.append(f"Contrarias: {', '.join(items)}")
        else:
            parts.append("Contrarias: nenhuma encontrada")

        return ". ".join(parts) + "."
