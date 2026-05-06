"""Active situacao definitions per TipoFonte.

Each TipoFonte has its own set of valid "active" statuses.
This is the single source of truth — import from here, never duplicate.

Actual values from corpus data:
    sumulas_vinculantes.json:           "vigente"
    sumulas_stf/stj/tst.json:          "vigente"
    ojs_tst.json:                      "vigente"
    temas_repercussao_geral_stf.json:  "tese_firmada"
    temas_repetitivos_stj.json:        "transitado"
"""

from __future__ import annotations

from juris.repertory.corpus.models import TipoFonte

ACTIVE_SITUACOES: dict[TipoFonte, frozenset[str]] = {
    TipoFonte.SUMULA_VINCULANTE: frozenset({"vigente"}),
    TipoFonte.RE_STF: frozenset({"tese_firmada"}),
    TipoFonte.RESP_REPETITIVO: frozenset({"transitado", "afetado"}),
    TipoFonte.SUMULA: frozenset({"vigente"}),
    TipoFonte.JURISPRUDENCIA_UNIFORME: frozenset({"vigente"}),
    TipoFonte.PRECEDENTE_LOCAL: frozenset({"vigente"}),
    TipoFonte.MODELO_PETICAO: frozenset({"vigente", "publicado"}),
    TipoFonte.DOUTRINA_PD: frozenset({"vigente", "publicado"}),
    TipoFonte.NOTICIA_TRIBUNAL: frozenset({"publicado"}),
    TipoFonte.ACORDAO_LANDMARK: frozenset({"vigente", "publicado"}),
    TipoFonte.ACORDAO_PUBLICADO: frozenset({"vigente", "publicado"}),
}


def is_active(tipo: TipoFonte, situacao: str) -> bool:
    """Check if a situacao is active for the given TipoFonte.

    Args:
        tipo: The type of jurisprudence source.
        situacao: The situacao string to check.

    Returns:
        True if the situacao is considered active for that TipoFonte.
    """
    return situacao in ACTIVE_SITUACOES.get(tipo, frozenset({"vigente"}))
