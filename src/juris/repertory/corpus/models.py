"""Domain models for the jurisprudence corpus hierarchy.

Defines the six weighted tiers of Brazilian legal precedents,
from binding precedents (Súmula Vinculante) to templates and news.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class TipoFonte(str, Enum):
    """Type of jurisprudence source, ordered by binding authority."""

    SUMULA_VINCULANTE = "sumula_vinculante"      # hierarquia=1
    RE_STF = "re_stf"                            # hierarquia=2
    RESP_REPETITIVO = "resp_repetitivo"          # hierarquia=3
    SUMULA = "sumula"                            # hierarquia=4
    JURISPRUDENCIA_UNIFORME = "jurisprudencia_uniforme"  # hierarquia=5
    PRECEDENTE_LOCAL = "precedente_local"        # hierarquia=6
    MODELO_PETICAO = "modelo_peticao"            # hierarquia=7
    DOUTRINA_PD = "doutrina_pd"                  # hierarquia=6
    NOTICIA_TRIBUNAL = "noticia_tribunal"        # hierarquia=7
    ACORDAO_LANDMARK = "acordao_landmark"        # hierarquia=3
    ACORDAO_PUBLICADO = "acordao_publicado"      # hierarquia=5


TIPO_HIERARQUIA: dict[TipoFonte, int] = {
    TipoFonte.SUMULA_VINCULANTE: 1,
    TipoFonte.RE_STF: 2,
    TipoFonte.RESP_REPETITIVO: 3,
    TipoFonte.SUMULA: 4,
    TipoFonte.JURISPRUDENCIA_UNIFORME: 5,
    TipoFonte.PRECEDENTE_LOCAL: 6,
    TipoFonte.MODELO_PETICAO: 7,
    TipoFonte.DOUTRINA_PD: 6,
    TipoFonte.NOTICIA_TRIBUNAL: 7,
    TipoFonte.ACORDAO_LANDMARK: 3,
    TipoFonte.ACORDAO_PUBLICADO: 5,
}

HIERARCHY_WEIGHTS: dict[int, float] = {
    1: 3.0,
    2: 2.5,
    3: 2.0,
    4: 1.5,
    5: 1.2,
    6: 1.0,
}

_HIERARCHY_LABELS: dict[int, str] = {
    1: "Súmula Vinculante",
    2: "Repercussão Geral (STF)",
    3: "Recurso Especial Repetitivo (STJ)",
    4: "Súmula",
    5: "Jurisprudência Uniforme",
    6: "Precedente Local",
}

_HIERARCHY_LABELS_DETAILED: dict[TipoFonte, str] = {
    TipoFonte.MODELO_PETICAO: "Modelo de Petição",
    TipoFonte.DOUTRINA_PD: "Doutrina (Domínio Público)",
    TipoFonte.NOTICIA_TRIBUNAL: "Notícia de Tribunal",
    TipoFonte.ACORDAO_LANDMARK: "Acórdão Landmark",
    TipoFonte.ACORDAO_PUBLICADO: "Acórdão Publicado",
}


@dataclass(frozen=True, slots=True)
class FonteJurisprudencia:
    """A source of jurisprudence in the corpus.

    Args:
        id: Unique identifier.
        tribunal: Court identifier (e.g., 'STF', 'STJ', 'TJMG').
        tipo: Type of source in the hierarchy.
        numero: Number/identifier of the precedent.
        ementa: Summary text (ementa) of the decision.
        texto_integral: Full text of the decision, if available.
        relator: Reporting justice name.
        data_julgamento: Date of judgment.
        temas: Subject tags.
        assuntos_cnj: CNJ subject codes.
        base_legal: Legal basis references.
        situacao: Status — vigente, superada, cancelada.
        hierarquia: Hierarchy level (1-6).
    """

    id: str
    tribunal: str
    tipo: TipoFonte
    numero: str
    ementa: str
    texto_integral: str | None = None
    relator: str | None = None
    data_julgamento: date | None = None
    temas: list[str] = field(default_factory=list)
    assuntos_cnj: list[str] = field(default_factory=list)
    base_legal: list[str] = field(default_factory=list)
    situacao: str = "vigente"
    hierarquia: int = 6
    data_aprovacao: date | None = None
    data_alteracao: date | None = None
    source_url: str | None = None
    source_publisher: str | None = None
    legal_basis: str | None = None

    @property
    def hierarchy_label(self) -> str:
        """Human-readable label for the hierarchy level."""
        detailed = _HIERARCHY_LABELS_DETAILED.get(self.tipo)
        if detailed:
            return detailed
        return _HIERARCHY_LABELS.get(self.hierarquia, f"Nível {self.hierarquia}")

    def __post_init__(self) -> None:
        """Validate hierarchy level."""
        if self.hierarquia == 7 and self.tipo in {
            TipoFonte.MODELO_PETICAO,
            TipoFonte.NOTICIA_TRIBUNAL,
        }:
            return
        if not 1 <= self.hierarquia <= 6:
            msg = f"hierarquia must be between 1 and 6, got {self.hierarquia}"
            raise ValueError(msg)
