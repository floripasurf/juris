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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, Protocol, cast

from juris.core.deid import deidentify, ensure_cloud_safe, reidentify
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
    # Módulo E — why ruling this way lowers the judge's decision cost (LLM text).
    fundamento_consequencialista: str | None = None


@dataclass(frozen=True, slots=True)
class ElementoCaso:
    """Módulo A — one classified element of the case."""

    texto: str
    tipo: Literal["fato", "prova", "inferencia", "lacuna", "risco"]


@dataclass(frozen=True, slots=True)
class ItemMatriz:
    """Módulo B — one claim mapped to existing evidence and gaps."""

    alegacao: str
    provas: list[str] = field(default_factory=list)  # existing evidence
    lacunas: list[str] = field(default_factory=list)  # missing evidence


@dataclass(frozen=True, slots=True)
class EstrategiaResult:
    """The recommended line plus the runners-up (transparency) — the Relatório.

    ``avisos_deontologicos`` (Módulo I) flags conduct vedada pelo CED/EOAB in the
    chosen line; ``revisao_humana_obrigatoria`` (auditor §6.14) is set when there
    are such flags, confidence is low, or the evidentiary support is weak (Módulo
    B). ``classificacao`` (A) and ``matriz_probatoria`` (B) enrich the Relatório.
    """

    escolhida: LinhaArgumentativa
    alternativas: list[LinhaArgumentativa]
    avisos_deontologicos: list[str] = field(default_factory=list)
    revisao_humana_obrigatoria: bool = False
    classificacao: list[ElementoCaso] = field(default_factory=list)
    matriz_probatoria: list[ItemMatriz] = field(default_factory=list)
    analise_adversario: str | None = None  # Módulo D (reuso do defesa_analyzer)


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


def _build_prompt(
    contexto: str,
    precedentes: Sequence[_Precedente],
    n: int,
    *,
    analise_adversario: str | None = None,
) -> str:
    fontes = "\n".join(f"- {p.source_id} (nível {p.hierarchy})" for p in precedentes)
    # Módulo D — give the adversary analysis so lines anticipate/neutralise it.
    adversario = (
        f"\nAnálise do adversário (antecipe e neutralize nos riscos/fundamentos):\n{analise_adversario}\n"
        if analise_adversario
        else ""
    )
    return (
        f"Caso:\n{contexto}\n{adversario}\nPrecedentes disponíveis (use os ids em 'citacoes'):\n{fontes}\n\n"
        f"Proponha {n} linhas argumentativas distintas como JSON: lista de objetos "
        '{"tese", "fundamentos": [...], "citacoes": [ids], "riscos": [...], '
        '"fundamento_consequencialista": "por que decidir assim reduz o custo decisório do julgador"}.'
    )


def _parse_candidatas(content: str) -> list[LinhaArgumentativa]:
    raw = json.loads(content)
    linhas: list[LinhaArgumentativa] = []
    for item in raw:
        consequencialista = item.get("fundamento_consequencialista")
        linhas.append(
            LinhaArgumentativa(
                tese=str(item.get("tese", "")),
                fundamentos=list(item.get("fundamentos", [])),
                citacoes=[str(c) for c in item.get("citacoes", [])],
                riscos=list(item.get("riscos", [])),
                fundamento_consequencialista=str(consequencialista) if consequencialista else None,
            )
        )
    return linhas


# ── Módulo A: classificação de elementos ──────────────────────────────────────
_TIPOS_ELEMENTO = frozenset({"fato", "prova", "inferencia", "lacuna", "risco"})

_SYSTEM_CLASSIFICACAO = (
    "Classifique cada elemento do caso FORNECIDO como fato, prova, inferencia, "
    "lacuna ou risco. Não invente fatos nem provas; o que faltar é lacuna."
)


def _parse_classificacao(content: str) -> list[ElementoCaso]:
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    elementos: list[ElementoCaso] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        tipo = str(item.get("tipo", "")).lower()
        texto = str(item.get("texto", "")).strip()
        if tipo in _TIPOS_ELEMENTO and texto:
            elementos.append(
                ElementoCaso(texto=texto, tipo=cast('Literal["fato", "prova", "inferencia", "lacuna", "risco"]', tipo))
            )
    return elementos


async def classificar_elementos(llm: AbstractLLM, contexto: str) -> list[ElementoCaso]:
    """Módulo A — classify the case into fato/prova/inferência/lacuna/risco."""
    response = await llm.complete(
        f'Caso:\n{contexto}\n\nRetorne JSON: lista de {{"texto", "tipo"}} '
        "(tipo ∈ fato|prova|inferencia|lacuna|risco).",
        system=_SYSTEM_CLASSIFICACAO,
        max_tokens=1000,
    )
    return _parse_classificacao(response.content)


# ── Módulo B: matriz probatória ───────────────────────────────────────────────
_SYSTEM_MATRIZ = (
    "Para cada alegação do caso FORNECIDO, liste as provas existentes e as "
    "lacunas (provas faltantes). Não invente provas; sem prova é lacuna."
)


def _parse_matriz(content: str) -> list[ItemMatriz]:
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    itens: list[ItemMatriz] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("alegacao", "")).strip():
            continue
        itens.append(
            ItemMatriz(
                alegacao=str(item["alegacao"]).strip(),
                provas=[str(p) for p in item.get("provas", [])],
                lacunas=[str(value) for value in item.get("lacunas", [])],
            )
        )
    return itens


async def montar_matriz(llm: AbstractLLM, contexto: str) -> list[ItemMatriz]:
    """Módulo B — map each claim to existing evidence and gaps."""
    response = await llm.complete(
        f'Caso:\n{contexto}\n\nRetorne JSON: lista de {{"alegacao", "provas": [...], '
        '"lacunas": [...]}}.',
        system=_SYSTEM_MATRIZ,
        max_tokens=1200,
    )
    return _parse_matriz(response.content)


def lastro_probatorio(matriz: list[ItemMatriz]) -> float:
    """Evidentiary support: fraction of claims backed by at least one prova.

    Empty matriz → 1.0 (nothing asserted, nothing to doubt). A low lastro means
    claims rest on gaps — the strategy needs mandatory human review (Módulo B).
    """
    if not matriz:
        return 1.0
    com_prova = sum(1 for item in matriz if item.provas)
    return round(com_prova / len(matriz), 4)


def _reid_linha(linha: LinhaArgumentativa, mapping: dict[str, str]) -> LinhaArgumentativa:
    return replace(
        linha,
        tese=reidentify(linha.tese, mapping),
        fundamentos=[reidentify(f, mapping) for f in linha.fundamentos],
        riscos=[reidentify(r, mapping) for r in linha.riscos],
        fundamento_consequencialista=(
            reidentify(linha.fundamento_consequencialista, mapping)
            if linha.fundamento_consequencialista
            else None
        ),
        # citacoes are precedent source_ids, not PII — left untouched.
    )


def _reidentificar_resultado(result: EstrategiaResult, mapping: dict[str, str]) -> EstrategiaResult:
    """Restore PII placeholders in every text field of the Relatório (ADR-0016)."""
    if not mapping:
        return result
    return replace(
        result,
        escolhida=_reid_linha(result.escolhida, mapping),
        alternativas=[_reid_linha(a, mapping) for a in result.alternativas],
        avisos_deontologicos=[reidentify(a, mapping) for a in result.avisos_deontologicos],
        classificacao=[replace(e, texto=reidentify(e.texto, mapping)) for e in result.classificacao],
        matriz_probatoria=[
            replace(
                m,
                alegacao=reidentify(m.alegacao, mapping),
                provas=[reidentify(p, mapping) for p in m.provas],
                lacunas=[reidentify(value, mapping) for value in m.lacunas],
            )
            for m in result.matriz_probatoria
        ],
        analise_adversario=(
            reidentify(result.analise_adversario, mapping) if result.analise_adversario else None
        ),
    )


class EstrategiaAgent:
    """Generates candidate lines via the LLM, then selects deterministically."""

    def __init__(self, llm: AbstractLLM) -> None:
        self._llm = llm

    async def propor(
        self,
        *,
        contexto: str,
        precedentes: Sequence[_Precedente],
        n: int = 3,
        modo: Literal["completo", "abreviado"] = "completo",
        analise_adversario: str | None = None,
        deidentificar: bool = False,
        ner_redactor: Callable[[str], list[str]] | None = None,
        allow_partial_deid: bool = False,
    ) -> EstrategiaResult:
        """Propose and select the best-grounded argumentative line.

        Args:
            modo: ``"completo"`` runs the full Relatório pipeline (Módulo A
                classify + Módulo B evidence matrix + line generation);
                ``"abreviado"`` skips A/B for a quick, single-call validation.
            analise_adversario: Módulo D — reuses the drafter's defesa_analyzer;
                fed to the line generation so lines anticipate the opponent.
            deidentificar: Strip PII (CPF/CNPJ/CNJ/OAB) from the context before
                any LLM call and restore it in the output (ADR-0016).
            ner_redactor: Optional NER (e.g. LeNER-Br) that also redacts free-text
                names — makes the de-id complete (cloud-safe).
            allow_partial_deid: Opt in to a partial (structured-only) de-id. Off
                by default: the agent **fails closed** before any cloud/browser
                call when names may remain — the gate isn't only in the router.
        """
        # Módulo 1 (ADR-0016) — de-identify before any LLM sees the case, and
        # enforce the cloud-safety gate here too (callers may use a cloud LLM).
        mapping: dict[str, str] = {}
        if deidentificar:
            sep = "\n###ADVERSARIO###\n"
            deid = deidentify(contexto + sep + (analise_adversario or ""), ner_redactor=ner_redactor)
            ensure_cloud_safe(deid, allow_partial=allow_partial_deid)
            mapping = deid.mapping
            contexto, _, adversario_deid = deid.text.partition(sep)
            analise_adversario = adversario_deid if analise_adversario else None

        classificacao: list[ElementoCaso] = []
        matriz: list[ItemMatriz] = []
        if modo == "completo":
            classificacao = await classificar_elementos(self._llm, contexto)
            matriz = await montar_matriz(self._llm, contexto)

        response = await self._llm.complete(
            _build_prompt(contexto, precedentes, n, analise_adversario=analise_adversario),
            system=_SYSTEM,
            max_tokens=1500,
        )
        candidatas = _parse_candidatas(response.content)
        result = selecionar_linha(candidatas, precedentes)

        lastro = lastro_probatorio(matriz)
        result = replace(
            result,
            classificacao=classificacao,
            matriz_probatoria=matriz,
            analise_adversario=analise_adversario,
            revisao_humana_obrigatoria=result.revisao_humana_obrigatoria or lastro < 0.5,
        )
        result = _reidentificar_resultado(result, mapping)  # restore PII for the lawyer
        logger.info(
            "estrategia_selecionada",
            modo=modo,
            candidatas=len(candidatas),
            score=result.escolhida.score,
            citacoes=len(result.escolhida.citacoes),
            elementos=len(classificacao),
            lastro=lastro,
            deidentificado=bool(mapping),
        )
        return result
