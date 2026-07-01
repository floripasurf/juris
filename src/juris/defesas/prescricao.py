"""Prescription verification engine."""

from __future__ import annotations

from datetime import date, timedelta

from juris.defesas.cc_prazos import buscar_prazo_prescricional
from juris.defesas.models import ResultadoDefesa, TipoDefesa


def verificar_prescricao(
    tipo_acao: str,
    data_fato: date,
    data_ajuizamento: date,
    causas_suspensao: list[tuple[date, date]] | None = None,
    causas_interrupcao: list[date] | None = None,
) -> ResultadoDefesa:
    """Check whether prescription has occurred for a given action.

    Strategy:
    1. Look up the applicable prescription period from cc_prazos.
    2. Calculate elapsed time from triggering event to filing.
    3. Subtract any suspension periods.
    4. If interruption causes exist, restart the clock from the last one.
    5. Compare effective elapsed time against the prescription period.

    Args:
        tipo_acao: Description of the action type (e.g. "Indenizatoria").
        data_fato: Date of the triggering event (fato gerador).
        data_ajuizamento: Date the action was filed.
        causas_suspensao: List of (start, end) tuples for suspension periods.
        causas_interrupcao: List of dates when prescription was interrupted.

    Returns:
        ResultadoDefesa with prescription analysis.
    """
    prazo = buscar_prazo_prescricional(tipo_acao)
    if prazo is None:
        return ResultadoDefesa(
            tipo=TipoDefesa.PRESCRICAO,
            aplicavel=False,
            confianca=0.3,
            fundamentacao=f"Tipo de acao '{tipo_acao}' nao encontrado na base de prazos prescricionais.",
            base_legal="",
            recomendacao="Verificar manualmente o prazo prescricional aplicavel.",
        )

    # Determine effective start date (considering interruptions)
    inicio_efetivo = data_fato
    if causas_interrupcao:
        # Interruption restarts the clock from the last interruption date
        ultima_interrupcao = max(causas_interrupcao)
        if ultima_interrupcao > data_fato:
            inicio_efetivo = ultima_interrupcao

    # Calculate total elapsed days
    dias_totais = (data_ajuizamento - inicio_efetivo).days

    # Subtract suspension periods
    dias_suspensos = 0
    if causas_suspensao:
        for inicio_susp, fim_susp in causas_suspensao:
            # Only count suspension that falls within the relevant period
            susp_start = max(inicio_susp, inicio_efetivo)
            susp_end = min(fim_susp, data_ajuizamento)
            if susp_end > susp_start:
                dias_suspensos += (susp_end - susp_start).days

    dias_efetivos = dias_totais - dias_suspensos

    # Convert prazo to days
    prazo_dias = int(prazo.prazo_anos * 365.25)

    # Check prescription
    prescrito = dias_efetivos > prazo_dias

    # Calculate the prescription deadline
    data_limite = inicio_efetivo + timedelta(days=prazo_dias + dias_suspensos)

    if prescrito:
        dias_excedidos = dias_efetivos - prazo_dias
        fundamentacao = (
            f"PRESCRICAO CONFIGURADA. "
            f"Prazo prescricional de {_format_prazo(prazo.prazo_anos)} ({prazo.base_legal}). "
            f"Termo inicial: {inicio_efetivo.strftime('%d/%m/%Y')}. "
            f"Data limite: {data_limite.strftime('%d/%m/%Y')}. "
            f"Ajuizamento em {data_ajuizamento.strftime('%d/%m/%Y')}, "
            f"{dias_excedidos} dias apos o prazo."
        )
        if dias_suspensos > 0:
            fundamentacao += f" Desconsiderados {dias_suspensos} dias de suspensao."
        if causas_interrupcao:
            fundamentacao += f" Ultima interrupcao em {inicio_efetivo.strftime('%d/%m/%Y')} (relogio reiniciado)."
        recomendacao = (
            "Alegar prescricao em preliminar de contestacao (Art. 487 II CPC). "
            "Direito potestativo do reu, materia de ordem publica."
        )
        confianca = 0.95
    else:
        dias_restantes = prazo_dias - dias_efetivos
        fundamentacao = (
            f"Prescricao NAO configurada. "
            f"Prazo prescricional de {_format_prazo(prazo.prazo_anos)} ({prazo.base_legal}). "
            f"Termo inicial: {inicio_efetivo.strftime('%d/%m/%Y')}. "
            f"Ajuizamento em {data_ajuizamento.strftime('%d/%m/%Y')}, "
            f"dentro do prazo ({dias_restantes} dias restantes)."
        )
        if dias_suspensos > 0:
            fundamentacao += f" Desconsiderados {dias_suspensos} dias de suspensao."
        if causas_interrupcao:
            fundamentacao += f" Ultima interrupcao em {inicio_efetivo.strftime('%d/%m/%Y')} (relogio reiniciado)."
        recomendacao = "Prescricao nao aplicavel. Avaliar outras defesas processuais."
        confianca = 0.90

    return ResultadoDefesa(
        tipo=TipoDefesa.PRESCRICAO,
        aplicavel=prescrito,
        confianca=confianca,
        fundamentacao=fundamentacao,
        base_legal=prazo.base_legal,
        recomendacao=recomendacao,
    )


def _format_prazo(anos: int | float) -> str:
    """Format a prazo in years to a human-readable string."""
    if isinstance(anos, float) and anos < 1:
        dias = int(anos * 365)
        return f"{dias} dias"
    if isinstance(anos, float) and not anos.is_integer():
        return f"{anos} anos"
    return f"{int(anos)} anos"
