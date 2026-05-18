"""Decadencia (lapse) verification engine."""

from __future__ import annotations

from datetime import date, timedelta

from juris.defesas.models import ResultadoDefesa, TipoDefesa


# Known decadencia periods
_PRAZOS_DECADENCIA: dict[str, tuple[int, str]] = {
    # CDC vicios
    "cdc vicio nao duravel": (30, "Art. 26 I CDC"),
    "cdc vicio duravel": (90, "Art. 26 II CDC"),
    # CC anulatoria
    "anulatoria": (1460, "Art. 178 CC"),  # 4 anos
    "anulacao casamento": (730, "Art. 1.560 CC"),  # 2 anos
    # Trabalhista
    "inquerito falta grave": (30, "Art. 853 CLT"),
}


def verificar_decadencia(
    tipo_direito: str,
    data_ciencia: date,
    data_exercicio: date | None = None,
) -> ResultadoDefesa:
    """Check whether decadencia (lapse) has occurred.

    Key difference from prescricao: decadencia does NOT admit suspension
    or interruption (Art. 207 CC), except in cases expressly provided by law.

    Args:
        tipo_direito: Description of the right subject to decadence.
        data_ciencia: Date the party became aware of the right/defect.
        data_exercicio: Date the right was exercised (filing/claim).
            Defaults to today if not provided.

    Returns:
        ResultadoDefesa with decadencia analysis.
    """
    data_exercicio = data_exercicio or date.today()

    # Look up decadence period
    normalized = tipo_direito.strip().lower()
    prazo_info = _PRAZOS_DECADENCIA.get(normalized)

    if prazo_info is None:
        # Partial match
        for key, info in _PRAZOS_DECADENCIA.items():
            if normalized in key or key in normalized:
                prazo_info = info
                break

    if prazo_info is None:
        return ResultadoDefesa(
            tipo=TipoDefesa.DECADENCIA,
            aplicavel=False,
            confianca=0.3,
            fundamentacao=f"Tipo de direito '{tipo_direito}' nao encontrado na base de prazos decadenciais.",
            base_legal="",
            recomendacao="Verificar manualmente se ha prazo decadencial aplicavel.",
        )

    prazo_dias, base_legal = prazo_info
    data_limite = data_ciencia + timedelta(days=prazo_dias)
    decaido = data_exercicio > data_limite

    if decaido:
        dias_excedidos = (data_exercicio - data_limite).days
        fundamentacao = (
            f"DECADENCIA CONFIGURADA. "
            f"Prazo decadencial de {_format_prazo_dias(prazo_dias)} ({base_legal}). "
            f"Ciencia em {data_ciencia.strftime('%d/%m/%Y')}. "
            f"Limite em {data_limite.strftime('%d/%m/%Y')}. "
            f"Exercicio em {data_exercicio.strftime('%d/%m/%Y')}, "
            f"{dias_excedidos} dias apos o prazo. "
            f"Decadencia nao admite suspensao ou interrupcao (Art. 207 CC)."
        )
        recomendacao = (
            "Alegar decadencia. Materia de ordem publica quando legal (Art. 210 CC); "
            "depende de alegacao da parte quando convencional (Art. 211 CC)."
        )
        confianca = 0.95
    else:
        dias_restantes = (data_limite - data_exercicio).days
        fundamentacao = (
            f"Decadencia NAO configurada. "
            f"Prazo de {_format_prazo_dias(prazo_dias)} ({base_legal}). "
            f"Ciencia em {data_ciencia.strftime('%d/%m/%Y')}. "
            f"Exercicio em {data_exercicio.strftime('%d/%m/%Y')}, "
            f"dentro do prazo ({dias_restantes} dias restantes)."
        )
        recomendacao = "Decadencia nao aplicavel."
        confianca = 0.90

    return ResultadoDefesa(
        tipo=TipoDefesa.DECADENCIA,
        aplicavel=decaido,
        confianca=confianca,
        fundamentacao=fundamentacao,
        base_legal=base_legal,
        recomendacao=recomendacao,
    )


def _format_prazo_dias(dias: int) -> str:
    """Format days to a human-readable string."""
    if dias < 365:
        return f"{dias} dias"
    anos = dias / 365
    if anos == int(anos):
        return f"{int(anos)} anos"
    return f"{anos:.1f} anos"
