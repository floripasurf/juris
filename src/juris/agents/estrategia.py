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
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, Protocol

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
    # Módulo C (hierarquização) + Módulo G (calibração de confiança), set by
    # selecionar_linha: principal > subsidiária > eventual; tom ∝ solidez.
    ordem: Literal["principal", "subsidiaria", "eventual"] = "subsidiaria"
    confianca: Literal["alta", "media", "baixa"] = "media"


@dataclass(frozen=True, slots=True)
class EstrategiaResult:
    """The recommended line plus the runners-up (transparency).

    ``avisos_deontologicos`` (Módulo I) flags conduct vedada pelo CED/EOAB in the
    chosen line; ``revisao_humana_obrigatoria`` (auditor §6.14) is set when there
    are such flags or confidence is low — the human always has the final say.
    """

    escolhida: LinhaArgumentativa
    alternativas: list[LinhaArgumentativa]
    avisos_deontologicos: list[str] = field(default_factory=list)
    revisao_humana_obrigatoria: bool = False


# Módulo I — deontological veto. High-precision patterns for conduct the CED/EOAB
# forbids in a thesis: claiming guaranteed success / inevitability of the outcome
# (firmeza do tom deve ser proporcional à solidez, never absolute).
_DEONTOLOGIA: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"êxito\s+garantid|garantia\s+de\s+êxito", re.IGNORECASE),
        "Afirma êxito garantido — vedado pelo CED (o tom deve ser proporcional à solidez).",
    ),
    (
        re.compile(r"(vitória|ganho|procedência|resultado)\s+(cert[oa]|garantid)", re.IGNORECASE),
        "Afirma resultado certo/garantido — vedado pelo CED.",
    ),
    (
        re.compile(r"inevitá(vel|veis)", re.IGNORECASE),
        "Afirma inevitabilidade do desfecho — vedado pelo CED.",
    ),
    (
        re.compile(r"sem\s+risco\s+algum|risco\s+zero|100\s*%\s+de\s+(êxito|chance)", re.IGNORECASE),
        "Linguagem de garantia de resultado (sem risco) — vedada pelo CED.",
    ),
]


def verificar_deontologia(linha: LinhaArgumentativa) -> list[str]:
    """Deterministic CED/EOAB guardrail over a line's tese + fundamentos.

    Returns human-readable avisos for forbidden conduct found (guaranteed
    success / inevitability). Empty when the line is sober. Flags, never silently
    suppresses — the lawyer decides (Módulo I).
    """
    texto = " ".join([linha.tese, *linha.fundamentos])
    avisos: list[str] = []
    for pattern, aviso in _DEONTOLOGIA:
        if pattern.search(texto) and aviso not in avisos:
            avisos.append(aviso)
    return avisos


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


def _ordem(rank: int) -> Literal["principal", "subsidiaria", "eventual"]:
    """Módulo C — rank → argument hierarchy."""
    if rank == 0:
        return "principal"
    if rank == 1:
        return "subsidiaria"
    return "eventual"


def _confianca(score: float) -> Literal["alta", "media", "baixa"]:
    """Módulo G — firmeza do tom proporcional à solidez (score → confiança)."""
    if score >= 0.66:
        return "alta"
    if score >= 0.4:
        return "media"
    return "baixa"


def selecionar_linha(
    candidatas: list[LinhaArgumentativa], precedentes: Sequence[_Precedente]
) -> EstrategiaResult:
    """Score every candidate, return the best as ``escolhida`` + the rest.

    Each line is also labelled with its place in the argument hierarchy (Módulo
    C) and a confidence calibrated from the score (Módulo G).
    """
    if not candidatas:
        msg = "Nenhuma linha argumentativa candidata para selecionar."
        raise ValueError(msg)
    scored = sorted(
        (replace(c, score=score_linha(c, precedentes)) for c in candidatas),
        key=lambda linha: linha.score,
        reverse=True,
    )
    ranked = [replace(c, ordem=_ordem(i), confianca=_confianca(c.score)) for i, c in enumerate(scored)]
    escolhida = ranked[0]
    avisos = verificar_deontologia(escolhida)  # Módulo I — deontological veto
    return EstrategiaResult(
        escolhida=escolhida,
        alternativas=ranked[1:],
        avisos_deontologicos=avisos,
        revisao_humana_obrigatoria=bool(avisos) or escolhida.confianca == "baixa",
    )


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
