"""Process context for defense analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class ProcessoContext:
    """Context data about a processo needed for defense analysis.

    Args:
        numero_cnj: Case number in CNJ format.
        tribunal: Tribunal ID (e.g. "tjmg").
        classe: Procedural class (e.g. "Acao de Cobranca").
        ramo_justica: Branch of justice (civel/trabalho/penal/eleitoral).
        data_ajuizamento: Date the action was filed.
        data_fato_gerador: Date of the triggering event.
        fase_atual: Current procedural phase.
        movimentos: List of movement dicts.
        partes: List of party dicts.
        valor_causa: Amount in dispute.
        assuntos: Subject matter codes/descriptions.
    """

    numero_cnj: str
    tribunal: str
    classe: str
    ramo_justica: str = "civel"
    data_ajuizamento: date | None = None
    data_fato_gerador: date | None = None
    fase_atual: str = ""
    movimentos: list[Any] = field(default_factory=list)
    partes: list[Any] = field(default_factory=list)
    valor_causa: float | None = None
    assuntos: list[str] = field(default_factory=list)
