"""Escavação fetchers — Source Mesh adapters that retrieve full text by CNJ.

The escavação executor is fetcher-agnostic; these adapt concrete providers to the
``EscavacaoFetcher`` port. DataJud is the available, public source — it returns
the process record + the **movimentos trail** (not the full acórdão; that lives in
gated jurisprudence databases, esaj cjsg etc.). So the DataJud adapter captures the
case's procedural history honestly; richer full-text sources plug in the same way.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from juris.escavacao.executor import InteiroTeor

if TYPE_CHECKING:
    from juris.escavacao.executor import EscavacaoFetcher
    from juris.escavacao.queue import AlvoEscavacao

_Consultar = Callable[..., "dict[str, Any] | None"]


def _source_to_text(source: dict[str, Any]) -> str:
    classe = source.get("classe", {}).get("nome", "")
    assuntos = "; ".join(a.get("nome", "") for a in source.get("assuntos", []))
    movimentos = source.get("movimentos", [])
    linhas = [f"- {m.get('dataHora', '')}: {m.get('nome', '')}" for m in movimentos]
    return f"Classe: {classe}\nAssunto: {assuntos}\nMovimentos:\n" + "\n".join(linhas)


class DataJudEscavacaoFetcher:
    """Fetches a case's record + movimentos trail from DataJud (public)."""

    def __init__(self, *, consultar: _Consultar | None = None) -> None:
        if consultar is None:
            from juris.datajud.client import consultar_processo

            consultar = consultar_processo
        self._consultar: _Consultar = consultar

    async def fetch(self, alvo: AlvoEscavacao) -> InteiroTeor | None:
        if not alvo.tribunal:
            return None  # DataJud indexes by tribunal; can't query without one
        source = await asyncio.to_thread(self._consultar, alvo.numero_cnj, alvo.tribunal)
        if not source:
            return None
        return InteiroTeor(
            numero_cnj=alvo.numero_cnj,
            texto=_source_to_text(source),
            fonte="datajud",
            origem_tema=alvo.origem_tema,
            parcial=True,  # movimentos trail, not the full acórdão
            metadata={
                "classe": source.get("classe", {}).get("nome", ""),
                "movimentos": len(source.get("movimentos", [])),
            },
        )


class FailoverFetcher:
    """Source Mesh for escavação — tries fetchers in order, best provenance wins.

    A **complete** full text (``parcial=False``, e.g. a real acórdão database)
    wins immediately; otherwise the first **partial** result (``parcial=True``,
    e.g. the DataJud movements trail) is the fallback. The winning InteiroTeor
    carries its source's ``fonte`` as provenance. Plug richer full-text sources
    ahead of DataJud as they become available.
    """

    def __init__(self, fetchers: list[EscavacaoFetcher]) -> None:
        self._fetchers = fetchers

    async def fetch(self, alvo: AlvoEscavacao) -> InteiroTeor | None:
        fallback: InteiroTeor | None = None
        for fetcher in self._fetchers:
            teor = await fetcher.fetch(alvo)
            if teor is None:
                continue
            if not teor.parcial:
                return teor  # a complete source wins over any partial trail
            if fallback is None:
                fallback = teor
        return fallback
