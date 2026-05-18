"""Preclusao (preclusion) verification engine."""

from __future__ import annotations

from typing import Any

from juris.defesas.models import ResultadoDefesa, TipoDefesa


def verificar_preclusao(
    tipo: TipoDefesa,
    movimentos: list[Any],
    prazo_rule: Any | None = None,
) -> ResultadoDefesa:
    """Check whether preclusion has occurred.

    Three types of preclusion:
    - Temporal (Art. 223 CPC): missed a deadline.
    - Consumativa (Art. 507 CPC): already exercised the right.
    - Logica (Art. 1.000 CPC): performed an incompatible act.

    Args:
        tipo: Type of preclusion to check (PRECLUSAO_TEMPORAL/CONSUMATIVA/LOGICA).
        movimentos: List of process movements (dicts with 'codigo', 'data', etc.).
        prazo_rule: Optional prazo rule for temporal preclusion checks.

    Returns:
        ResultadoDefesa with preclusion analysis.
    """
    if tipo == TipoDefesa.PRECLUSAO_TEMPORAL:
        return _verificar_temporal(movimentos, prazo_rule)
    if tipo == TipoDefesa.PRECLUSAO_CONSUMATIVA:
        return _verificar_consumativa(movimentos)
    if tipo == TipoDefesa.PRECLUSAO_LOGICA:
        return _verificar_logica(movimentos)

    return ResultadoDefesa(
        tipo=tipo,
        aplicavel=False,
        confianca=0.3,
        fundamentacao=f"Tipo de preclusao '{tipo.value}' nao reconhecido.",
        base_legal="",
        recomendacao="Verificar manualmente.",
    )


def _verificar_temporal(
    movimentos: list[Any],
    prazo_rule: Any | None,
) -> ResultadoDefesa:
    """Check temporal preclusion (missed deadline)."""
    if prazo_rule is None:
        return ResultadoDefesa(
            tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
            aplicavel=False,
            confianca=0.3,
            fundamentacao="Sem regra de prazo para verificar preclusao temporal.",
            base_legal="Art. 223 CPC",
            recomendacao="Informar regra de prazo para analise.",
        )

    # Check if there's a movement indicating the deadline was missed
    # Look for "certidao de decurso de prazo" or similar
    decurso_codes = {493, 123}  # Anotacao, Certificacao
    has_decurso = any(
        _get_mov_codigo(m) in decurso_codes
        for m in movimentos
    )

    if has_decurso:
        return ResultadoDefesa(
            tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
            aplicavel=True,
            confianca=0.80,
            fundamentacao=(
                "Preclusao temporal identificada. "
                "Movimento indicando decurso de prazo encontrado nos autos. "
                "A parte perdeu a faculdade processual por nao exercer "
                "no prazo legal ou judicial."
            ),
            base_legal="Art. 223 CPC",
            recomendacao=(
                "Verificar se houve justa causa para devolucao de prazo "
                "(Art. 223 par.1 CPC). Caso contrario, a preclusao e definitiva."
            ),
        )

    return ResultadoDefesa(
        tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
        aplicavel=False,
        confianca=0.60,
        fundamentacao="Nenhum indicativo de decurso de prazo nos movimentos analisados.",
        base_legal="Art. 223 CPC",
        recomendacao="Verificar se o prazo ja transcorreu sem manifestacao.",
    )


def _verificar_consumativa(movimentos: list[Any]) -> ResultadoDefesa:
    """Check consumptive preclusion (right already exercised)."""
    # Look for duplicate acts (e.g., two contestacoes, two resources)
    act_codes: dict[int, int] = {}
    for m in movimentos:
        code = _get_mov_codigo(m)
        if code and code > 0:
            act_codes[code] = act_codes.get(code, 0) + 1

    # Codes that should not repeat: contestacao, recurso, replica
    non_repeatable = {584, 197, 195, 198, 199, 585}  # juntada contestacao, apelacao, etc.
    duplicated = {code for code, count in act_codes.items() if count > 1 and code in non_repeatable}

    if duplicated:
        return ResultadoDefesa(
            tipo=TipoDefesa.PRECLUSAO_CONSUMATIVA,
            aplicavel=True,
            confianca=0.75,
            fundamentacao=(
                "Preclusao consumativa identificada. "
                "Ato processual ja exercido pela parte e repetido nos autos. "
                "Uma vez praticado o ato, nao pode ser repetido."
            ),
            base_legal="Art. 507 CPC",
            recomendacao="Impugnar o ato repetido, alegando preclusao consumativa.",
        )

    return ResultadoDefesa(
        tipo=TipoDefesa.PRECLUSAO_CONSUMATIVA,
        aplicavel=False,
        confianca=0.60,
        fundamentacao="Nenhum ato processual repetido identificado nos movimentos.",
        base_legal="Art. 507 CPC",
        recomendacao="Preclusao consumativa nao identificada.",
    )


def _verificar_logica(movimentos: list[Any]) -> ResultadoDefesa:
    """Check logical preclusion (incompatible act performed)."""
    # Classic case: accepting sentence then appealing
    acceptance_codes = {1051, 466, 467}  # Homologacao de acordo, etc.
    appeal_codes = {197, 195, 198, 200, 201, 202, 460}  # Various appeals

    mov_codes = [_get_mov_codigo(m) for m in movimentos]
    has_acceptance = any(c in acceptance_codes for c in mov_codes)
    has_appeal = any(c in appeal_codes for c in mov_codes)

    if has_acceptance and has_appeal:
        return ResultadoDefesa(
            tipo=TipoDefesa.PRECLUSAO_LOGICA,
            aplicavel=True,
            confianca=0.70,
            fundamentacao=(
                "Preclusao logica identificada. "
                "Parte praticou ato incompativel com o direito exercido "
                "(ex: aceitacao de decisao seguida de recurso)."
            ),
            base_legal="Art. 1.000 CPC",
            recomendacao="Alegar preclusao logica. A parte que aceitou nao pode recorrer.",
        )

    return ResultadoDefesa(
        tipo=TipoDefesa.PRECLUSAO_LOGICA,
        aplicavel=False,
        confianca=0.50,
        fundamentacao="Nenhum ato logicamente incompativel identificado nos movimentos.",
        base_legal="Art. 1.000 CPC",
        recomendacao="Preclusao logica nao identificada.",
    )


def _get_mov_codigo(mov: Any) -> int:
    """Extract movement code from a movement dict or object."""
    if isinstance(mov, dict):
        return mov.get("codigo", 0) or 0
    return getattr(mov, "codigo_nacional", 0) or 0
