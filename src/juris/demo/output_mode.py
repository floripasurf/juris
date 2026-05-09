"""Output mode selection for demo runs (Sprint 17).

Two operator-selected modes — no automatic routing or numeric scoring yet:

- ``MINUTA_SUGERIDA`` (default): the existing pipeline output, labeled
  *MINUTA SUGERIDA* with a mandatory lawyer-review banner. Used when the
  operator believes the corpus and template support are sufficient to
  generate a draft for the lawyer to revise.

- ``RASCUNHO_PESQUISA``: a structured research memo (análise jurídica +
  argumentos sugeridos + riscos + esqueleto) instead of a petition draft.
  Operator-selected via ``juris demo --modo rascunho-pesquisa`` when the
  case feels weakly supported. The artifact is **not** a fileable petition
  and the limitation is encoded in the artifact itself (different filename,
  loud banner, no petition prose).

Codex Sprint 17 ruling: do not compute a numeric ``prontidão_da_minuta``
score yet. Without real smoke-test data, a heuristic would manufacture
false confidence — worse than no formula. Mode selection stays manual until
the first pilot run produces calibration data.
"""

from __future__ import annotations

from enum import Enum


class OutputMode(str, Enum):
    """Operator-selected output mode for ``juris demo``."""

    MINUTA_SUGERIDA = "minuta-sugerida"
    RASCUNHO_PESQUISA = "rascunho-pesquisa"


# Banner placed above the petition draft in MINUTA SUGERIDA mode. Distinct
# from DEMO_BANNER (which is about fixture-vs-real); this banner is about
# the mode itself and applies to both demo and real runs.
MINUTA_SUGERIDA_BANNER: str = (
    "> 📝 **MINUTA SUGERIDA — REVISÃO OBRIGATÓRIA**\n"
    ">\n"
    "> Esta minuta foi gerada por IA com citações verificadas no\n"
    "> repertório. **Antes de qualquer uso processual, advogado(a)\n"
    "> inscrito(a) na OAB deve revisar integralmente, validar a\n"
    "> aplicabilidade ao caso concreto e assumir responsabilidade**\n"
    "> técnica pela peça.\n"
)

# Banner for RASCUNHO DE PESQUISA mode. Loud enough that the limitation is
# unmistakable: this is a research memo, not a petition.
RASCUNHO_PESQUISA_BANNER: str = (
    "> 🔍 **RASCUNHO DE PESQUISA — NÃO É PEÇA PRONTA PARA PROTOCOLO**\n"
    ">\n"
    "> Este documento é um **memorando de pesquisa** com análise jurídica,\n"
    "> argumentos sugeridos, riscos e esqueleto de petição. **Não\n"
    "> substitui a redação da peça pelo(a) advogado(a) inscrito(a) na\n"
    "> OAB.** Use como ponto de partida para a redação manual.\n"
)


# Filename used by the artifacts module for each mode's primary draft.
# RASCUNHO mode uses a distinct filename so it can never be mistaken for a
# fileable petition draft on the operator's filesystem.
DRAFT_FILENAME: dict[OutputMode, str] = {
    OutputMode.MINUTA_SUGERIDA: "draft.md",
    OutputMode.RASCUNHO_PESQUISA: "rascunho-pesquisa.md",
}


def banner_for(mode: OutputMode) -> str:
    """Return the mode banner string."""
    if mode is OutputMode.MINUTA_SUGERIDA:
        return MINUTA_SUGERIDA_BANNER
    if mode is OutputMode.RASCUNHO_PESQUISA:
        return RASCUNHO_PESQUISA_BANNER
    raise ValueError(f"Unknown output mode: {mode}")


def label_for(mode: OutputMode) -> str:
    """Human-readable label used in manifest, audit, and CLI output."""
    if mode is OutputMode.MINUTA_SUGERIDA:
        return "MINUTA SUGERIDA"
    if mode is OutputMode.RASCUNHO_PESQUISA:
        return "RASCUNHO DE PESQUISA"
    raise ValueError(f"Unknown output mode: {mode}")


def draft_filename(mode: OutputMode) -> str:
    """Return the filename for the mode's primary draft artifact."""
    try:
        return DRAFT_FILENAME[mode]
    except KeyError as exc:
        raise ValueError(f"Unknown output mode: {mode}") from exc


__all__ = [
    "DRAFT_FILENAME",
    "MINUTA_SUGERIDA_BANNER",
    "OutputMode",
    "RASCUNHO_PESQUISA_BANNER",
    "banner_for",
    "draft_filename",
    "label_for",
]
