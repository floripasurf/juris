"""Directed-scraping queue — the escavação work-list (SCHEMA §4/§5).

The espinha (súmulas/enunciados) carries, for free, the ``precedentes_processos``
that formed each thesis — the court's own list of leading cases. This module
turns those CNJs into a **prioritised, deduped queue of full-text targets**: the
moat is built by deep-scraping these, not by crawling blindly. Priority follows
the authority of the source that surfaced the case (a CNJ cited by a nível-1 STJ
thesis is scraped before one cited only by a local enunciado).

The actual full-text fetch is a Source Mesh job (DataJud/MNI/scraper) — this is
the queue that drives it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _Espinha(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def hierarquia(self) -> int: ...

    @property
    def precedentes_processos(self) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class AlvoEscavacao:
    """One full-text target for directed scraping."""

    numero_cnj: str
    origem_tema: str  # espinha id that surfaced this case
    prioridade: float  # higher = scrape sooner (by source authority)
    tribunal: str | None  # derived from the CNJ


def _prioridade(hierarquia: int) -> float:
    """Nível 1 (most authoritative source) → highest priority."""
    return float(7 - max(1, min(6, hierarquia)))


def construir_fila(
    precedentes: list[_Espinha] | list[Any], *, max_alvos: int | None = None
) -> list[AlvoEscavacao]:
    """Build the prioritised, deduped escavação queue from espinha entries.

    Args:
        precedentes: Espinha entries carrying ``precedentes_processos`` (CNJs).
        max_alvos: Optional cap on the number of targets returned.

    Returns:
        Deduped :class:`AlvoEscavacao` list, highest-authority origin first.
    """
    from juris.search.cnj_router import cnj_to_court

    best: dict[str, AlvoEscavacao] = {}
    for esp in precedentes:
        prioridade = _prioridade(esp.hierarquia)
        for cnj in esp.precedentes_processos:
            existing = best.get(cnj)
            if existing is not None and existing.prioridade >= prioridade:
                continue
            best[cnj] = AlvoEscavacao(
                numero_cnj=cnj,
                origem_tema=esp.id,
                prioridade=prioridade,
                tribunal=cnj_to_court(cnj),
            )

    fila = sorted(best.values(), key=lambda a: a.prioridade, reverse=True)
    return fila[:max_alvos] if max_alvos is not None else fila
