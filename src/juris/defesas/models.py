"""Domain models for the defesas (procedural defenses) engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CodigoProcessual(str, Enum):
    """Procedural code systems in Brazilian law."""

    CPC = "CPC"
    CPP = "CPP"
    CLT = "CLT"
    CPE = "CPE"
    CC = "CC"


class TipoDefesa(str, Enum):
    """Types of procedural defenses available."""

    PRESCRICAO = "prescricao"
    PRESCRICAO_INTERCORRENTE = "prescricao_intercorrente"
    DECADENCIA = "decadencia"
    PRECLUSAO_TEMPORAL = "preclusao_temporal"
    PRECLUSAO_CONSUMATIVA = "preclusao_consumativa"
    PRECLUSAO_LOGICA = "preclusao_logica"
    COISA_JULGADA = "coisa_julgada"
    LITISPENDENCIA = "litispendencia"
    ILEGITIMIDADE = "ilegitimidade"
    INCOMPETENCIA = "incompetencia"
    INEPCIA = "inepcia"
    FALTA_INTERESSE = "falta_interesse"


@dataclass(frozen=True, slots=True)
class PrazoInstituto:
    """Prescription/decadence period for a specific type of action.

    Args:
        tipo_acao: Description of the action type (e.g. "Indenizatoria").
        prazo_anos: Period in years (can be fractional, e.g. 0.5 for 6 months).
        base_legal: Legal basis (e.g. "Art. 206 par.3 V CC").
        termo_inicial: When the period starts running.
        notas: Additional notes or caveats.
    """

    tipo_acao: str
    prazo_anos: int | float
    base_legal: str
    termo_inicial: str
    notas: str


@dataclass(frozen=True, slots=True)
class InstitutoProcessual:
    """A procedural defense institute with its legal requirements.

    Args:
        nome: Display name of the institute.
        codigo_processual: Which procedural code governs it.
        artigos: List of relevant articles.
        descricao: Brief description.
        tipo: The defense type enum value.
        prazos: Applicable periods (if any).
        requisitos: Requirements for applicability.
        excecoes: Exceptions that may prevent applicability.
        jurisprudencia_chave: Key case law references.
    """

    nome: str
    codigo_processual: CodigoProcessual
    artigos: list[str]
    descricao: str
    tipo: TipoDefesa
    prazos: list[PrazoInstituto] = field(default_factory=list)
    requisitos: list[str] = field(default_factory=list)
    excecoes: list[str] = field(default_factory=list)
    jurisprudencia_chave: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResultadoDefesa:
    """Result of checking a single defense applicability.

    Args:
        tipo: Which defense was checked.
        aplicavel: Whether the defense applies.
        confianca: Confidence level (0.0 to 1.0).
        fundamentacao: Reasoning for the conclusion.
        base_legal: Legal basis cited.
        recomendacao: Recommended action for the lawyer.
    """

    tipo: TipoDefesa
    aplicavel: bool
    confianca: float
    fundamentacao: str
    base_legal: str
    recomendacao: str


@dataclass(frozen=True, slots=True)
class DefesaReport:
    """Full defense analysis report for a processo.

    Args:
        numero_cnj: Case number in CNJ format.
        defesas_identificadas: List of defense check results.
        summary: Human-readable summary.
    """

    numero_cnj: str
    defesas_identificadas: list[ResultadoDefesa] = field(default_factory=list)
    summary: str = ""
