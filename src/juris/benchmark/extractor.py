"""Auto-extraction pipeline for benchmark pairs from petition corpus."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM
from juris.repertory.citation_lookup import resolve_narrative_citation
from juris.repertory.retrieval.service import RepertoryService

logger = get_logger(__name__)


@dataclass(slots=True)
class ExtractedPair:
    """A benchmark pair: thesis + expected source_ids."""

    thesis: str
    expected_source_ids: list[str]
    paraphrases: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: str = ""
    status: str = "pending"  # pending, accepted, rejected, skipped
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "thesis": self.thesis,
            "expected_source_ids": self.expected_source_ids,
            "paraphrases": self.paraphrases,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "status": self.status,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExtractedPair:
        return cls(
            thesis=d["thesis"],
            expected_source_ids=d["expected_source_ids"],
            paraphrases=d.get("paraphrases", []),
            confidence=d.get("confidence", 0.0),
            provenance=d.get("provenance", ""),
            status=d.get("status", "pending"),
            rejection_reason=d.get("rejection_reason", ""),
        )


EXTRACTION_PROMPT = (
    "Analise a secao abaixo de uma peticao juridica brasileira.\n\n"
    "Secao:\n{section_text}\n\n"
    "Extraia:\n"
    "1. A tese juridica principal sendo argumentada (uma frase, voz do advogado)\n"
    "2. Todas as autoridades citadas como suporte (numeros de Sumula, REsp, RE, Tema, artigos)\n\n"
    "Responda em JSON:\n"
    '{{"thesis": "...", "authorities": ["Sumula 297 STJ", "REsp 1.234.567/SP", ...]}}'
)

PARAPHRASE_PROMPT = (
    "Tese juridica original:\n{thesis}\n\n"
    "Gere 2 reformulacoes dessa tese:\n"
    "1. Uma versao formal (linguagem de peticao)\n"
    "2. Uma versao como pergunta (como um advogado pesquisaria)\n\n"
    "Responda em JSON:\n"
    '{{"formal": "...", "question": "..."}}'
)


async def extract_pairs_from_text(
    text: str,
    section_name: str,
    repertory: RepertoryService,
    llm: AbstractLLM,
) -> list[ExtractedPair]:
    """Extract benchmark pairs from a petition text section.

    Args:
        text: Petition section text.
        section_name: Source identifier for provenance.
        repertory: For resolving citations.
        llm: For thesis extraction and paraphrasing.

    Returns:
        List of extracted pairs with confidence scores.
    """
    pairs: list[ExtractedPair] = []

    # 1. Extract thesis and authorities via LLM
    try:
        prompt = EXTRACTION_PROMPT.format(section_text=text[:2000])
        response = await llm.complete(
            prompt=prompt,
            temperature=0.1,
            max_tokens=512,
        )
        data = json.loads(response.content)
        thesis = data.get("thesis", "")
        authorities = data.get("authorities", [])
    except Exception:
        logger.warning("extraction_failed", section=section_name)
        return []

    if not thesis or not authorities:
        return []

    # 2. Resolve each authority against repertory
    resolved_ids: list[str] = []
    for auth in authorities:
        found, source_id = resolve_narrative_citation(auth, repertory)
        if found and source_id:
            resolved_ids.append(source_id)

    if not resolved_ids:
        return []

    # 3. Compute confidence
    confidence = len(resolved_ids) / len(authorities) if authorities else 0.0
    if len(authorities) == 1 and len(resolved_ids) == 1:
        confidence = min(confidence + 0.2, 1.0)

    # 4. Generate paraphrases
    paraphrases: list[str] = []
    try:
        para_prompt = PARAPHRASE_PROMPT.format(thesis=thesis)
        para_response = await llm.complete(
            prompt=para_prompt,
            temperature=0.3,
            max_tokens=256,
        )
        para_data = json.loads(para_response.content)
        if para_data.get("formal"):
            paraphrases.append(para_data["formal"])
        if para_data.get("question"):
            paraphrases.append(para_data["question"])
    except Exception:
        logger.debug("paraphrase_generation_failed", section=section_name)

    pair = ExtractedPair(
        thesis=thesis,
        expected_source_ids=resolved_ids,
        paraphrases=paraphrases,
        confidence=confidence,
        provenance=section_name,
    )
    pairs.append(pair)

    return pairs


def save_pairs(pairs: list[ExtractedPair], path: Path) -> None:
    """Save extracted pairs to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.to_dict() for p in pairs]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pairs(path: Path) -> list[ExtractedPair]:
    """Load pairs from JSON file."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ExtractedPair.from_dict(d) for d in data]


def load_curated_pairs(path: Path) -> list[ExtractedPair]:
    """Load only accepted pairs from JSON file."""
    return [p for p in load_pairs(path) if p.status == "accepted"]
