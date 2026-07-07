"""Domain models for the jurisprudence corpus hierarchy.

Defines the six weighted tiers of Brazilian legal precedents,
from binding precedents (Súmula Vinculante) to templates and news.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class TipoFonte(StrEnum):
    """Type of jurisprudence source, ordered by binding authority."""

    SUMULA_VINCULANTE = "sumula_vinculante"  # hierarquia=1
    RE_STF = "re_stf"  # hierarquia=2
    RESP_REPETITIVO = "resp_repetitivo"  # hierarquia=3
    SUMULA = "sumula"  # hierarquia=4
    JURISPRUDENCIA_UNIFORME = "jurisprudencia_uniforme"  # hierarquia=5
    PRECEDENTE_LOCAL = "precedente_local"  # hierarquia=6
    MODELO_PETICAO = "modelo_peticao"  # hierarquia=7
    DOUTRINA_PD = "doutrina_pd"  # hierarquia=6
    NOTICIA_TRIBUNAL = "noticia_tribunal"  # hierarquia=7
    ACORDAO_LANDMARK = "acordao_landmark"  # hierarquia=3
    ACORDAO_PUBLICADO = "acordao_publicado"  # hierarquia=5
    PECA_ESCRITORIO = "peca_escritorio"  # hierarquia=7 — peça protocolada do próprio escritório
    NOTA_INTERNA = "nota_interna"  # hierarquia=7 — tese/playbook interno
    DOUTRINA_PRIVADA = "doutrina_privada"  # hierarquia=6 — obra licenciada/própria (rights_basis obrigatório)


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
    TipoFonte.PECA_ESCRITORIO: 7,
    TipoFonte.NOTA_INTERNA: 7,
    TipoFonte.DOUTRINA_PRIVADA: 6,
}


class UsoFonte(StrEnum):
    """Como uma fonte pode ser usada pelo pipeline (spec Biblioteca L1).

    FUNDAMENTO: citável como autoridade jurídica (entra em allowed_source_ids).
    ESTILO: ensina estrutura/forma; NUNCA é citada — o verifier bloqueia.
    """

    FUNDAMENTO = "fundamento"
    ESTILO = "estilo"


TIPO_USO_DEFAULT: dict[TipoFonte, UsoFonte] = {
    TipoFonte.SUMULA_VINCULANTE: UsoFonte.FUNDAMENTO,
    TipoFonte.RE_STF: UsoFonte.FUNDAMENTO,
    TipoFonte.RESP_REPETITIVO: UsoFonte.FUNDAMENTO,
    TipoFonte.SUMULA: UsoFonte.FUNDAMENTO,
    TipoFonte.JURISPRUDENCIA_UNIFORME: UsoFonte.FUNDAMENTO,
    TipoFonte.PRECEDENTE_LOCAL: UsoFonte.FUNDAMENTO,
    TipoFonte.MODELO_PETICAO: UsoFonte.ESTILO,
    TipoFonte.DOUTRINA_PD: UsoFonte.FUNDAMENTO,
    TipoFonte.NOTICIA_TRIBUNAL: UsoFonte.ESTILO,
    TipoFonte.ACORDAO_LANDMARK: UsoFonte.FUNDAMENTO,
    TipoFonte.ACORDAO_PUBLICADO: UsoFonte.FUNDAMENTO,
    TipoFonte.PECA_ESCRITORIO: UsoFonte.ESTILO,
    TipoFonte.NOTA_INTERNA: UsoFonte.ESTILO,
    TipoFonte.DOUTRINA_PRIVADA: UsoFonte.FUNDAMENTO,
}

# Valores string dos tipos estilo-only, para os SQLs/payloads das stores.
ESTILO_SOURCE_TYPES: frozenset[str] = frozenset(
    t.value for t, uso in TIPO_USO_DEFAULT.items() if uso is UsoFonte.ESTILO
)

# Base de direitos exigida para doutrina (spec L1): sem base válida, não ingere.
RIGHTS_BASIS_VALUES: frozenset[str] = frozenset(
    {"dominio_publico", "obra_do_escritorio", "licenca_do_escritorio", "ato_oficial"}
)


def resolve_uso(tipo: TipoFonte | str | None, override: str | None = None) -> UsoFonte:
    """Resolve o uso efetivo: override explícito > default do tipo > fundamento.

    Args:
        tipo: TipoFonte (ou seu valor string) do documento; None quando desconhecido.
        override: valor explícito de uso vindo do upload/registro ("" = ausente).

    Returns:
        UsoFonte efetivo.

    Raises:
        ValueError: override não-vazio que não é um UsoFonte válido.
    """
    if override:
        return UsoFonte(override)  # ValueError natural para valor inválido
    if tipo is None:
        return UsoFonte.FUNDAMENTO
    try:
        tipo_enum = tipo if isinstance(tipo, TipoFonte) else TipoFonte(str(tipo))
    except ValueError:
        return UsoFonte.FUNDAMENTO
    return TIPO_USO_DEFAULT.get(tipo_enum, UsoFonte.FUNDAMENTO)


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
