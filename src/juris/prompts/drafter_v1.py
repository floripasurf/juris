"""Drafter prompt templates — v1 with citation contract."""
from __future__ import annotations

from typing import Any

PROMPT_VERSION = "drafter_v1"

SYSTEM_PROMPT = (
    "Voce e um advogado brasileiro experiente especializado em redacao de peticoes. "
    "Voce DEVE seguir rigorosamente as REGRAS ABSOLUTAS DE CITACAO abaixo.\n\n"
    "## REGRAS ABSOLUTAS DE CITACAO\n"
    "1. Voce so pode citar fontes que aparecem na lista JURISPRUDENCIA DISPONIVEL abaixo.\n"
    "2. Cada citacao no texto deve usar o formato [CITE:source_id], onde source_id "
    "e exatamente o id de uma fonte da lista.\n"
    "3. Nao invente numeros de processo, sumulas, temas, recursos repetitivos ou "
    "acordaos. Se a fonte nao esta na lista, voce NAO pode cita-la — formule o "
    "argumento sem citacao ou peca por mais pesquisa.\n"
    "4. Nao cite por titulo generico ('a doutrina majoritaria'); use a fonte especifica.\n"
    "5. Cada [CITE:source_id] que voce usar deve ser apropriado ao argumento — nao "
    "use uma fonte so para parecer fundamentado.\n"
    "6. Se a lista disser 'Nenhuma jurisprudencia encontrada', NAO mencione REsp, RE, "
    "Tema, Sumula ou acordao; diga que nao ha precedente verificado disponivel.\n\n"
    "## FORMATO DE SAIDA\n"
    "- Gere a peticao em Markdown.\n"
    "- A secao CONTRAPONTO PREVISTO NAO faz parte da peticao. E uma nota estrategica "
    "interna para o advogado, separada do corpo da peticao.\n"
    "- Mantenha tom formal juridico em portugues.\n"
)

DRAFT_PROMPT = (
    "## DADOS DO PROCESSO\n"
    "{case_context}\n\n"
    "{defesa_section}"
    "## TESE\n"
    "{thesis}\n\n"
    "## JURISPRUDENCIA DISPONIVEL (FAVORAVEL)\n"
    "{supporting_sources}\n\n"
    "## JURISPRUDENCIA CONTRARIA (para contraponto)\n"
    "{opposing_sources}\n\n"
    "{style_section}"
    "{custom_instructions}"
    "{revision_feedback}"
    "{tone_section}"
    "## TAREFA\n"
    "Redija uma peticao de {tipo_peticao} completa seguindo a estrutura adequada. "
    "Use os marcadores [CITE:source_id] conforme o contrato de citacoes. "
    "Inclua a secao CONTRAPONTO PREVISTO ao final."
)

THESIS_INFERENCE_PROMPT = (
    "Dados do processo:\n"
    "Classe: {classe}\n"
    "Assuntos: {assuntos}\n"
    "Tribunal: {tribunal}\n"
    "Tipo de peticao: {tipo_peticao}\n\n"
    "Com base nesses dados, formule a tese juridica principal (em 1-2 frases) "
    "que deve ser defendida nesta peticao. Responda APENAS com a tese, sem explicacoes."
)

ESTRUTURA_REFERENCIAL = (
    "ESTRUTURA REFERENCIAL (modelo {source_publisher} para {tipo_peticao}):\n"
    "Seções típicas:\n"
    "{secoes_esperadas}\n"
    "INSTRUÇÃO: Use esta estrutura como referência. Adapte ao caso concreto.\n"
)


def format_template_scaffold(
    source_publisher: str,
    tipo_peticao: str,
    section_titles: list[str],
) -> str:
    """Format a template scaffold for insertion into the style section."""
    secoes = "\n".join(f"- {s}" for s in section_titles)
    return ESTRUTURA_REFERENCIAL.format(
        source_publisher=source_publisher,
        tipo_peticao=tipo_peticao,
        secoes_esperadas=secoes,
    )


def format_case_context(context: dict[str, Any]) -> str:
    """Format case context dict as readable text for the prompt."""
    parts: list[str] = []
    if context.get("numero_cnj"):
        parts.append(f"- **Processo:** {context['numero_cnj']}")
    if context.get("tribunal"):
        parts.append(f"- **Tribunal:** {context['tribunal']}")
    if context.get("classe"):
        parts.append(f"- **Classe:** {context['classe']}")
    if context.get("ramo_justica"):
        parts.append(f"- **Ramo:** {context['ramo_justica']}")
    if context.get("assuntos"):
        parts.append(f"- **Assuntos:** {', '.join(context['assuntos'])}")
    if context.get("valor_causa"):
        parts.append(f"- **Valor da causa:** R$ {context['valor_causa']:,.2f}")
    if context.get("fase_atual"):
        parts.append(f"- **Fase atual:** {context['fase_atual']}")
    return "\n".join(parts) if parts else "Dados nao disponiveis."


def format_sources(sources: list[Any]) -> str:
    """Format retrieval results as source list for the prompt."""
    if not sources:
        return "Nenhuma jurisprudencia encontrada."
    parts: list[str] = []
    for src in sources:
        entry = (
            f"- **[{src.source_id}]** {src.hierarchy_label} — {src.tribunal}\n"
            f"  {src.texto[:300]}"
        )
        if hasattr(src, "base_legal") and src.base_legal:
            entry += f"\n  Base legal: {', '.join(src.base_legal)}"
        parts.append(entry)
    return "\n\n".join(parts)
