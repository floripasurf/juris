"""Result models, enums, and request/response types for party search."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FonteOrigem(StrEnum):
    """Source channel that produced a search result."""

    ESAJ = "esaj"
    EPROC = "eproc"
    EJEF = "ejef"
    DATAJUD = "datajud"
    PROJUDI = "projudi"


@dataclass(frozen=True, slots=True)
class BuscaRequest:
    """Search request parameters."""

    nome: str | None = None
    cpf: str | None = None
    oab: str | None = None
    tribunais: list[str] | None = None
    max_per_tribunal: int = 20

    def __post_init__(self) -> None:
        if not self.nome and not self.cpf and not self.oab:
            msg = "At least one of nome, cpf, or oab must be provided"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ResultadoBusca:
    """Single result from one channel."""

    numero_cnj: str
    tribunal: str
    fonte: FonteOrigem
    classe: str
    assunto: str
    orgao_julgador: str
    data_ajuizamento: str
    grau: str
    ultima_atualizacao: str
    polo_ativo: list[str] = field(default_factory=list)
    polo_passivo: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResultadoConsolidado:
    """Deduplicated, enriched result with corroboration score."""

    numero_cnj: str
    tribunal: str
    classe: str
    assunto: str
    orgao_julgador: str
    data_ajuizamento: str
    grau: str
    ultima_atualizacao: str
    polo_ativo: list[str] = field(default_factory=list)
    polo_passivo: list[str] = field(default_factory=list)
    fontes: list[FonteOrigem] = field(default_factory=list)
    confianca: float = 0.0
    enriquecido: bool = False
    dados_datajud: dict[str, Any] | None = None
    movimentos_count: int = 0
    valor_causa: float | None = None


@dataclass(frozen=True, slots=True)
class RelatoriosBusca:
    """Full search report from orchestrator."""

    request: BuscaRequest
    resultados: list[ResultadoConsolidado]
    total_encontrado: int
    tribunais_consultados: int
    tribunais_com_erro: list[str]
    canais_usados: list[FonteOrigem]
    duracao_segundos: float
    do_cache: bool = False
    provedores_pulados: list[str] = field(default_factory=list)
