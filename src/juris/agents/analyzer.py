"""Movement analyzer agent — rule-first, LLM only for ambiguous cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from juris.core.observability import get_logger
from juris.mni.parsers.processo import Movimento
from juris.mni.tpu import (
    CategoriaSemantica,
    Urgencia,
    categorize_movement,
    get_entry,
    get_urgency,
    is_actionable,
    is_high_confidence,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Result of analyzing a single movement."""

    movimento_id: str
    codigo_tpu: int | None
    descricao: str
    data_hora: datetime | None  # None when the MNI movement had no parseable dataHora
    categoria: CategoriaSemantica
    urgencia: Urgencia
    requer_acao: bool
    recomendacao: str
    confianca: float
    prazo_dias_uteis: int | None = None
    metodo: str = "rule"  # "rule" or "llm"


@dataclass(frozen=True, slots=True)
class ProcessoAnalysis:
    """Full analysis of a processo's movements."""

    numero_cnj: str
    tribunal: str
    total_movimentos: int
    analyzed: list[AnalysisResult] = field(default_factory=list)
    actionable: list[AnalysisResult] = field(default_factory=list)
    llm_calls: int = 0
    rule_classified: int = 0

    @property
    def summary(self) -> str:
        if not self.actionable:
            return f"{self.numero_cnj}: sem ações pendentes ({self.total_movimentos} movimentos)"
        urgentes = [a for a in self.actionable if a.urgencia in (Urgencia.CRITICA, Urgencia.ALTA)]
        return (
            f"{self.numero_cnj}: {len(self.actionable)} ações pendentes "
            f"({len(urgentes)} urgentes), "
            f"{self.rule_classified} rule / {self.llm_calls} LLM"
        )


def _data_tag(data_hora: datetime | None) -> str:
    """ISO date for an id/prompt, or a stable ``sem-data`` marker when absent.

    A movement with no parseable date must not fabricate one (the prazo engine routes
    it to manual review); here we only need a stable, non-crashing tag.
    """
    return data_hora.isoformat() if data_hora is not None else "sem-data"


def _rule_based_recommendation(entry_or_code: int, categoria: CategoriaSemantica) -> str:
    """Generate a recommendation based purely on TPU rules."""
    entry = get_entry(entry_or_code)
    desc = entry.descricao if entry else f"Código {entry_or_code}"

    recommendations: dict[CategoriaSemantica, str] = {
        CategoriaSemantica.SENTENCA: f"Sentença proferida ({desc}). Verificar resultado e avaliar recurso.",
        CategoriaSemantica.DECISAO_RECORRIVEL: f"Decisão publicada ({desc}). Analisar conteúdo e prazo recursal.",
        CategoriaSemantica.PRAZO_ABERTO: f"Prazo aberto ({desc}). Verificar prazo e providenciar manifestação.",
        CategoriaSemantica.PAUTA_MARCADA: f"Audiência/pauta ({desc}). Verificar data e preparar.",
        CategoriaSemantica.CITACAO: f"Citação ({desc}). Apresentar contestação no prazo legal.",
        CategoriaSemantica.INTIMACAO: f"Intimação ({desc}). Verificar conteúdo e tomar providências.",
        CategoriaSemantica.RECURSO: f"Recurso ({desc}). Acompanhar tramitação e prazo de contrarrazões.",
        CategoriaSemantica.ACORDO: f"Acordo ({desc}). Verificar termos e cumprimento.",
        CategoriaSemantica.TRANSITO_JULGADO: f"Trânsito em julgado ({desc}). Iniciar cumprimento de sentença.",
        CategoriaSemantica.TUTELA: f"Tutela ({desc}). Verificar cumprimento imediato da decisão.",
        CategoriaSemantica.CUMPRIMENTO: f"Cumprimento ({desc}). Acompanhar execução.",
        CategoriaSemantica.EXECUCAO: f"Execução ({desc}). Verificar constrição e tomar providências.",
        CategoriaSemantica.PERICIA: f"Perícia ({desc}). Verificar quesitos e prazo.",
        CategoriaSemantica.JUNTADA_DOCUMENTO: f"Documento juntado ({desc}). Verificar conteúdo se relevante.",
        CategoriaSemantica.NOISE: "Movimentação administrativa. Nenhuma ação necessária.",
    }
    return recommendations.get(categoria, f"Movimentação: {desc}. Avaliar necessidade de ação.")


def analyze_movimento_rule(mov: Movimento) -> AnalysisResult:
    """Classify a movement using only TPU rules (no LLM)."""
    codigo = mov.codigo_nacional or 0
    categoria = categorize_movement(codigo)
    urgencia = get_urgency(codigo)
    entry = get_entry(codigo)
    requer_acao = entry.requer_acao if entry else is_actionable(categoria)
    recomendacao = _rule_based_recommendation(codigo, categoria)

    confianca = 0.95 if is_high_confidence(codigo) else 0.5

    return AnalysisResult(
        movimento_id=mov.id_movimento or f"mov_{codigo}_{_data_tag(mov.data_hora)}",
        codigo_tpu=codigo if codigo else None,
        descricao=mov.descricao or "",
        data_hora=mov.data_hora,
        categoria=categoria,
        urgencia=urgencia,
        requer_acao=requer_acao,
        recomendacao=recomendacao,
        confianca=confianca,
        metodo="rule",
    )


async def analyze_movimento_llm(
    mov: Movimento,
    numero_cnj: str,
    tribunal: str,
    llm: Any,
) -> AnalysisResult:
    """Classify a movement using LLM (for ambiguous/unclassified cases)."""
    from juris.prompts.analyzer_v1 import CLASSIFY_PROMPT, CLASSIFY_SCHEMA, SYSTEM_PROMPT

    codigo = mov.codigo_nacional or 0
    prompt = CLASSIFY_PROMPT.format(
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        codigo_tpu=codigo,
        descricao=mov.descricao or "",
        complemento=mov.complemento or "",
        data_hora=_data_tag(mov.data_hora),
    )

    response = await llm.complete(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        schema=CLASSIFY_SCHEMA,
        temperature=0.0,
    )

    structured = response.structured or {}
    cat_str = structured.get("categoria", "unclassified")
    try:
        categoria = CategoriaSemantica(cat_str)
    except ValueError:
        categoria = CategoriaSemantica.UNCLASSIFIED

    urg_str = structured.get("urgencia", "media")
    try:
        urgencia = Urgencia(urg_str)
    except ValueError:
        urgencia = Urgencia.MEDIA

    return AnalysisResult(
        movimento_id=mov.id_movimento or f"mov_{codigo}_{_data_tag(mov.data_hora)}",
        codigo_tpu=codigo if codigo else None,
        descricao=mov.descricao or "",
        data_hora=mov.data_hora,
        categoria=categoria,
        urgencia=urgencia,
        requer_acao=structured.get("requer_acao", False),
        recomendacao=structured.get("recomendacao", "Avaliar necessidade de ação."),
        confianca=structured.get("confianca", 0.7),
        prazo_dias_uteis=structured.get("prazo_dias_uteis"),
        metodo="llm",
    )


async def analyze_processo(
    numero_cnj: str,
    tribunal: str,
    movimentos: list[Movimento],
    llm: Any | None = None,
    skip_noise: bool = True,
) -> ProcessoAnalysis:
    """Analyze all movements of a processo.

    Rule-first strategy:
    1. Classify via TPU code → if high-confidence, done
    2. If UNCLASSIFIED and LLM available → call LLM
    3. If no LLM → mark as unclassified with low confidence

    Args:
        numero_cnj: Case number.
        tribunal: Tribunal ID.
        movimentos: List of movements to analyze.
        llm: Optional LLM backend for ambiguous cases.
        skip_noise: If True, exclude NOISE from actionable results.
    """
    results: list[AnalysisResult] = []
    actionable: list[AnalysisResult] = []
    llm_calls = 0
    rule_classified = 0

    for mov in movimentos:
        rule_result = analyze_movimento_rule(mov)

        if rule_result.confianca >= 0.9:
            result = rule_result
            rule_classified += 1
        elif llm is not None and rule_result.categoria == CategoriaSemantica.UNCLASSIFIED:
            try:
                result = await analyze_movimento_llm(mov, numero_cnj, tribunal, llm)
                llm_calls += 1
            except Exception:
                logger.warning("llm_classify_failed", movimento_id=rule_result.movimento_id)
                result = rule_result
                rule_classified += 1
        else:
            result = rule_result
            rule_classified += 1

        results.append(result)

        if result.requer_acao:
            if skip_noise and result.categoria == CategoriaSemantica.NOISE:
                continue
            actionable.append(result)

    actionable.sort(key=lambda a: (
        list(Urgencia).index(a.urgencia),
        a.data_hora is None,  # undated movements sort last within an urgency band
        a.data_hora or datetime.max.replace(tzinfo=UTC),
    ))

    logger.info(
        "processo_analyzed",
        numero_cnj=numero_cnj,
        total=len(movimentos),
        actionable=len(actionable),
        rule_classified=rule_classified,
        llm_calls=llm_calls,
    )

    return ProcessoAnalysis(
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        total_movimentos=len(movimentos),
        analyzed=results,
        actionable=actionable,
        llm_calls=llm_calls,
        rule_classified=rule_classified,
    )
