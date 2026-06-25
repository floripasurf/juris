"""Argumentative-line selector — Stage 2 of the ADR-0017 filter.

Turns the Stage-1 ranked+verified precedents into a recommended *linha
argumentativa*. The LLM proposes candidate lines (judge-panel — diverse angles);
the selection is then **deterministic and auditable**: each candidate is scored
by how well it is grounded in the verified precedents (no hallucinated
citations), the authority of what it cites, and a risk penalty. The winner is
returned with the runners-up, so the lawyer sees the alternatives — the LLM
never makes the final call by itself.

"Fit to the local decider" (escavação data) is a future component; absent it,
the score degrades to grounding + authority.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

from juris.core.observability import get_logger

if TYPE_CHECKING:
    from juris.llm.base import AbstractLLM

logger = get_logger(__name__)


class _Precedente(Protocol):
    @property
    def source_id(self) -> str: ...

    @property
    def hierarchy(self) -> int: ...


@dataclass(frozen=True, slots=True)
class LinhaArgumentativa:
    """One candidate line of argument."""

    tese: str
    fundamentos: list[str] = field(default_factory=list)
    citacoes: list[str] = field(default_factory=list)  # claimed precedent source_ids
    riscos: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class EstrategiaResult:
    """The recommended line plus the runners-up (transparency)."""

    escolhida: LinhaArgumentativa
    alternativas: list[LinhaArgumentativa]


def _autoridade(hierarchy: int) -> float:
    h = max(1, min(6, hierarchy))
    return (6 - h) / 5


def score_linha(linha: LinhaArgumentativa, precedentes: Sequence[_Precedente]) -> float:
    """Deterministic score: grounding + authority of citations − risk.

    Grounding is the fraction of claimed citations that are *real* verified
    precedents — a line citing precedents not in the Stage-1 set is penalised,
    which is how we keep the strategy honest ("não inventar jurisprudência").
    """
    ids = {p.source_id for p in precedentes}
    cited_ids = set(linha.citacoes)
    grounding = (sum(1 for c in linha.citacoes if c in ids) / len(linha.citacoes)) if linha.citacoes else 0.0

    cited = [p for p in precedentes if p.source_id in cited_ids]
    autoridade = (sum(_autoridade(p.hierarchy) for p in cited) / len(cited)) if cited else 0.0

    risco = 0.1 * len(linha.riscos)
    return round(max(0.0, 0.6 * grounding + 0.4 * autoridade - risco), 4)


def selecionar_linha(
    candidatas: list[LinhaArgumentativa], precedentes: Sequence[_Precedente]
) -> EstrategiaResult:
    """Score every candidate, return the best as ``escolhida`` + the rest."""
    if not candidatas:
        msg = "Nenhuma linha argumentativa candidata para selecionar."
        raise ValueError(msg)
    scored = sorted(
        (replace(c, score=score_linha(c, precedentes)) for c in candidatas),
        key=lambda linha: linha.score,
        reverse=True,
    )
    return EstrategiaResult(escolhida=scored[0], alternativas=scored[1:])


_SYSTEM = (
    "Você é um(a) estrategista jurídico(a). A partir do caso e dos precedentes "
    "FORNECIDOS (e somente deles), proponha linhas argumentativas distintas. "
    "Cada citação deve referenciar o id de um precedente da lista. Não invente "
    "precedentes."
)


def _build_prompt(contexto: str, precedentes: Sequence[_Precedente], n: int) -> str:
    fontes = "\n".join(f"- {p.source_id} (nível {p.hierarchy})" for p in precedentes)
    return (
        f"Caso:\n{contexto}\n\nPrecedentes disponíveis (use os ids em 'citacoes'):\n{fontes}\n\n"
        f"Proponha {n} linhas argumentativas distintas como JSON: lista de objetos "
        '{"tese", "fundamentos": [...], "citacoes": [ids], "riscos": [...]}.'
    )


def _parse_candidatas(content: str) -> list[LinhaArgumentativa]:
    raw = json.loads(content)
    linhas: list[LinhaArgumentativa] = []
    for item in raw:
        linhas.append(
            LinhaArgumentativa(
                tese=str(item.get("tese", "")),
                fundamentos=list(item.get("fundamentos", [])),
                citacoes=[str(c) for c in item.get("citacoes", [])],
                riscos=list(item.get("riscos", [])),
            )
        )
    return linhas


class EstrategiaAgent:
    """Generates candidate lines via the LLM, then selects deterministically."""

    def __init__(self, llm: AbstractLLM) -> None:
        self._llm = llm

    async def propor(
        self, *, contexto: str, precedentes: Sequence[_Precedente], n: int = 3
    ) -> EstrategiaResult:
        """Propose and select the best-grounded argumentative line."""
        response = await self._llm.complete(
            _build_prompt(contexto, precedentes, n),
            system=_SYSTEM,
            max_tokens=1500,
        )
        candidatas = _parse_candidatas(response.content)
        result = selecionar_linha(candidatas, precedentes)
        logger.info(
            "estrategia_selecionada",
            candidatas=len(candidatas),
            score=result.escolhida.score,
            citacoes=len(result.escolhida.citacoes),
        )
        return result
