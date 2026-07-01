"""Art. 337 CPC preliminary defense identification."""

from __future__ import annotations

from juris.defesas.context import ProcessoContext
from juris.defesas.models import ResultadoDefesa, TipoDefesa


def identificar_preliminares(context: ProcessoContext) -> list[ResultadoDefesa]:
    """Identify applicable preliminary defenses from Art. 337 CPC.

    Checks the following preliminaries based on ProcessoContext:
    - Coisa julgada
    - Litispendencia
    - Incompetencia
    - Inepcia da inicial
    - Ilegitimidade de parte
    - Falta de interesse de agir

    Args:
        context: ProcessoContext with case information.

    Returns:
        List of ResultadoDefesa for each check performed.
    """
    resultados: list[ResultadoDefesa] = []

    resultados.append(_check_coisa_julgada(context))
    resultados.append(_check_litispendencia(context))
    resultados.append(_check_incompetencia(context))
    resultados.append(_check_inepcia(context))
    resultados.append(_check_ilegitimidade(context))
    resultados.append(_check_falta_interesse(context))

    return resultados


def _check_coisa_julgada(context: ProcessoContext) -> ResultadoDefesa:
    """Check for coisa julgada indicators in movements."""
    # Look for transito em julgado in movements
    transito_codes = {970, 22001}
    has_transito = any(_get_mov_code(m) in transito_codes for m in context.movimentos)

    if has_transito:
        return ResultadoDefesa(
            tipo=TipoDefesa.COISA_JULGADA,
            aplicavel=True,
            confianca=0.80,
            fundamentacao=(
                "Indicativo de coisa julgada. Movimento de transito em julgado "
                "identificado nos autos. Verificar identidade de partes, "
                "pedido e causa de pedir com acao anterior."
            ),
            base_legal="Art. 502-508 CPC",
            recomendacao=(
                "Alegar coisa julgada em preliminar (Art. 337 VII CPC). Necessario comprovar triplice identidade."
            ),
        )

    return ResultadoDefesa(
        tipo=TipoDefesa.COISA_JULGADA,
        aplicavel=False,
        confianca=0.60,
        fundamentacao="Nenhum indicativo de coisa julgada nos movimentos.",
        base_legal="Art. 502-508 CPC",
        recomendacao="Verificar se ha acao anterior com triplice identidade.",
    )


def _check_litispendencia(context: ProcessoContext) -> ResultadoDefesa:
    """Check for litispendencia indicators."""
    # Rule-based: can only flag potential litispendencia, not confirm it
    return ResultadoDefesa(
        tipo=TipoDefesa.LITISPENDENCIA,
        aplicavel=False,
        confianca=0.40,
        fundamentacao=(
            "Litispendencia requer verificacao de acao identica em tramitacao "
            "(mesmas partes, pedido e causa de pedir). "
            "Analise automatica limitada sem acesso a outros processos."
        ),
        base_legal="Art. 337 par.1-3 CPC",
        recomendacao=("Pesquisar no sistema do tribunal se ha acao identica em tramitacao contra as mesmas partes."),
    )


def _check_incompetencia(context: ProcessoContext) -> ResultadoDefesa:
    """Check for incompetencia based on ramo_justica and tribunal."""
    # Basic competence checks
    ramo = context.ramo_justica.lower()
    classe = context.classe.lower() if context.classe else ""
    tribunal = context.tribunal.lower()

    issues: list[str] = []

    # Trabalhista in justica comum
    if ramo == "trabalho" and not tribunal.startswith("trt"):
        issues.append("Acao trabalhista em tribunal que nao e da Justica do Trabalho.")

    # Civel in justica do trabalho
    if ramo == "civel" and tribunal.startswith("trt"):
        issues.append("Acao civel em tribunal da Justica do Trabalho.")

    # Penal em vara civel
    if ramo == "penal" and "civel" in classe:
        issues.append("Materia penal em vara civel.")

    if issues:
        return ResultadoDefesa(
            tipo=TipoDefesa.INCOMPETENCIA,
            aplicavel=True,
            confianca=0.70,
            fundamentacao=("Possivel incompetencia identificada: " + "; ".join(issues)),
            base_legal="Art. 64 CPC (absoluta) / Art. 65 CPC (relativa)",
            recomendacao=(
                "Alegar incompetencia. Se absoluta (materia/pessoa/funcional), "
                "pode ser alegada a qualquer tempo. Se relativa (territorial), "
                "deve ser em preliminar de contestacao."
            ),
        )

    return ResultadoDefesa(
        tipo=TipoDefesa.INCOMPETENCIA,
        aplicavel=False,
        confianca=0.50,
        fundamentacao="Nenhuma incompatibilidade evidente entre materia e juizo.",
        base_legal="Art. 64-65 CPC",
        recomendacao="Verificar competencia territorial se aplicavel.",
    )


def _check_inepcia(context: ProcessoContext) -> ResultadoDefesa:
    """Check for inepcia da inicial indicators."""
    issues: list[str] = []

    if not context.assuntos:
        issues.append("Assunto nao informado.")

    if not context.classe:
        issues.append("Classe processual nao informada.")

    if context.valor_causa is not None and context.valor_causa <= 0:
        issues.append("Valor da causa zerado ou negativo.")

    if issues:
        return ResultadoDefesa(
            tipo=TipoDefesa.INEPCIA,
            aplicavel=True,
            confianca=0.50,
            fundamentacao=(
                "Possiveis indicios de inepcia: "
                + "; ".join(issues)
                + " Verificar se a peticao inicial preenche os requisitos do Art. 319 CPC."
            ),
            base_legal="Art. 330 CPC",
            recomendacao=(
                "Avaliar se a inicial e inepta (Art. 330 CPC). Alegar em preliminar de contestacao se aplicavel."
            ),
        )

    return ResultadoDefesa(
        tipo=TipoDefesa.INEPCIA,
        aplicavel=False,
        confianca=0.50,
        fundamentacao="Nenhum indicio evidente de inepcia da inicial.",
        base_legal="Art. 330 CPC",
        recomendacao="Analisar a peticao inicial para verificar requisitos do Art. 319 CPC.",
    )


def _check_ilegitimidade(context: ProcessoContext) -> ResultadoDefesa:
    """Check for ilegitimidade de parte indicators."""
    # Rule-based: limited without analyzing the actual petition
    has_partes = bool(context.partes)
    return ResultadoDefesa(
        tipo=TipoDefesa.ILEGITIMIDADE,
        aplicavel=False,
        confianca=0.30,
        fundamentacao=(
            "Legitimidade de parte requer analise da relacao juridica material. "
            f"{'Partes informadas nos autos.' if has_partes else 'Partes nao informadas.'} "
            "Analise automatica limitada."
        ),
        base_legal="Art. 17 CPC",
        recomendacao=(
            "Verificar se as partes sao titulares da relacao juridica discutida. "
            "Alegar ilegitimidade ativa ou passiva em preliminar se aplicavel."
        ),
    )


def _check_falta_interesse(context: ProcessoContext) -> ResultadoDefesa:
    """Check for falta de interesse de agir indicators."""
    return ResultadoDefesa(
        tipo=TipoDefesa.FALTA_INTERESSE,
        aplicavel=False,
        confianca=0.30,
        fundamentacao=(
            "Interesse de agir requer analise de necessidade, utilidade e adequacao "
            "da via processual eleita. Analise automatica limitada."
        ),
        base_legal="Art. 17 CPC",
        recomendacao=("Verificar se a parte tem necessidade da tutela jurisdicional e se a via processual e adequada."),
    )


def _get_mov_code(mov: object) -> int:
    """Extract movement code from a movement dict or object."""
    if isinstance(mov, dict):
        return mov.get("codigo", 0) or 0
    return getattr(mov, "codigo_nacional", 0) or 0
