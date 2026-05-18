"""Intercurrent prescription verification (Art. 921 par.4 CPC)."""

from __future__ import annotations

from datetime import date, timedelta

from juris.defesas.models import ResultadoDefesa, TipoDefesa


def verificar_prescricao_intercorrente(
    data_ultimo_ato: date,
    data_suspensao: date | None,
    prazo_original_anos: int | float,
) -> ResultadoDefesa:
    """Check whether intercurrent prescription has occurred during execution phase.

    Art. 921 par.4 CPC: after 1 year of suspension (par.1), the prescription
    period of the original action starts running. The period is the same as
    the original action (Sumula 150 STJ).

    Args:
        data_ultimo_ato: Date of the last meaningful act in the execution.
        data_suspensao: Date the process was suspended (Art. 921 par.1).
            If None, uses data_ultimo_ato.
        prazo_original_anos: Prescription period of the original action in years.

    Returns:
        ResultadoDefesa with intercurrent prescription analysis.
    """
    if prazo_original_anos <= 0:
        return ResultadoDefesa(
            tipo=TipoDefesa.PRESCRICAO_INTERCORRENTE,
            aplicavel=False,
            confianca=0.3,
            fundamentacao="Prazo original invalido ou nao informado.",
            base_legal="Art. 921 par.4 CPC",
            recomendacao="Verificar o prazo prescricional da acao originaria.",
        )

    # If no suspension date provided, use last act date
    inicio_suspensao = data_suspensao or data_ultimo_ato

    # After 1 year of suspension, prescription starts running
    inicio_prescricao = inicio_suspensao + timedelta(days=365)

    # Prescription period = same as original action
    prazo_dias = int(prazo_original_anos * 365.25)
    data_limite = inicio_prescricao + timedelta(days=prazo_dias)

    hoje = date.today()
    prescrito = hoje >= data_limite

    if prescrito:
        dias_excedidos = (hoje - data_limite).days
        fundamentacao = (
            f"PRESCRICAO INTERCORRENTE CONFIGURADA. "
            f"Suspensao em {inicio_suspensao.strftime('%d/%m/%Y')}. "
            f"Apos 1 ano de suspensao (Art. 921 par.1 CPC), "
            f"inicio da prescricao em {inicio_prescricao.strftime('%d/%m/%Y')}. "
            f"Prazo de {_format_prazo(prazo_original_anos)} (Sumula 150 STJ). "
            f"Limite em {data_limite.strftime('%d/%m/%Y')}, "
            f"excedido em {dias_excedidos} dias."
        )
        recomendacao = (
            "Requerer reconhecimento da prescricao intercorrente (Art. 921 par.4 CPC). "
            "O juiz deve ouvir as partes antes de declarar (Art. 921 par.5 CPC)."
        )
        confianca = 0.90
    else:
        dias_restantes = (data_limite - hoje).days
        fundamentacao = (
            f"Prescricao intercorrente NAO configurada. "
            f"Suspensao em {inicio_suspensao.strftime('%d/%m/%Y')}. "
            f"Prescricao iniciaria em {inicio_prescricao.strftime('%d/%m/%Y')}. "
            f"Limite em {data_limite.strftime('%d/%m/%Y')} "
            f"({dias_restantes} dias restantes)."
        )
        recomendacao = "Prescricao intercorrente ainda nao consumada. Monitorar prazo."
        confianca = 0.85

    return ResultadoDefesa(
        tipo=TipoDefesa.PRESCRICAO_INTERCORRENTE,
        aplicavel=prescrito,
        confianca=confianca,
        fundamentacao=fundamentacao,
        base_legal="Art. 921 par.4 CPC + Sumula 150 STJ",
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
