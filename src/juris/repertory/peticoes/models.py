"""Petition template models — types and structures for Brazilian legal petitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TipoPeticao(str, Enum):
    """Types of legal petitions in Brazilian law."""

    INICIAL = "inicial"
    CONTESTACAO = "contestacao"
    APELACAO = "apelacao"
    AGRAVO_INSTRUMENTO = "agravo_instrumento"
    EMBARGOS_DECLARACAO = "embargos_declaracao"
    RECURSO_ESPECIAL = "recurso_especial"
    RECURSO_EXTRAORDINARIO = "recurso_extraordinario"
    CONTRARRAZOES = "contrarrazoes"
    CUMPRIMENTO_SENTENCA = "cumprimento_sentenca"
    EXECUCAO = "execucao"


@dataclass(frozen=True, slots=True)
class SecaoPeticao:
    """A section within a petition template.

    Args:
        ordem: Section order number.
        titulo: Section title.
        proposito: Purpose of the section.
        exemplo_resumido: Brief example text for the section.
    """

    ordem: int
    titulo: str
    proposito: str
    exemplo_resumido: str


@dataclass(frozen=True, slots=True)
class TemplatePeticao:
    """A petition template with structure and argumentation patterns.

    Args:
        id: Unique template identifier.
        tipo: Type of petition.
        titulo: Template title.
        ramo_direito: Area of law.
        fase_processual: Procedural phase.
        estrutura: List of sections composing the petition.
        cadeia_argumentativa: Reasoning chain steps.
        padroes_argumentacao: Argumentation patterns used.
        fundamento_legal: Legal foundations (articles, statutes).
        texto_integral: Full original text if available.
    """

    id: str
    tipo: TipoPeticao
    titulo: str
    ramo_direito: str
    fase_processual: str
    estrutura: list[SecaoPeticao] = field(default_factory=list)
    cadeia_argumentativa: list[str] = field(default_factory=list)
    padroes_argumentacao: list[str] = field(default_factory=list)
    fundamento_legal: list[str] = field(default_factory=list)
    texto_integral: str | None = None
