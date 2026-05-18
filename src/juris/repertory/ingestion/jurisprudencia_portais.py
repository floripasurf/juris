"""Ingester for published acórdãos from tribunal portals.

GATED: ToS compliance check required per portal before enabling HTTP fetching.
Rate limit: ≤1 req/2sec, off-peak windows only.
"""

from __future__ import annotations

import logging
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

_PORTAIS: dict[str, str] = {
    "STF": "https://portal.stf.jus.br/jurisprudencia/",
    "STJ": "https://scon.stj.jus.br/SCON/",
    "TST": "https://jurisprudencia.tst.jus.br/",
    "TJSP": "https://esaj.tjsp.jus.br/cjsg/",
    "TJMG": "https://www4.tjmg.jus.br/juridico/sf/proc_resultado2.jsp",
    "TJRJ": "https://www1.tjrj.jus.br/gedcacheweb/",
    "TJRS": "https://www.tjrs.jus.br/site/jurisprudencia/",
}


class JurisprudenciaPortaisIngester(CorpusIngester):
    """Ingests published acórdãos from Brazilian tribunal portals.

    tipo: ACORDAO_PUBLICADO, hierarquia: 5.
    Rate limit: ≤1 req/2sec, off-peak only (22h–06h BRT).

    GATED: Each portal requires individual ToS compliance sign-off.
    See data/tos_compliance_log.md for per-portal status.

    Args:
        portais: Set of portal keys to ingest from (subset of _PORTAIS keys).
                 Defaults to all configured portais.
        limit: Maximum number of entries to ingest per portal (None for all).
    """

    PORTAIS: dict[str, str] = _PORTAIS

    def __init__(
        self,
        portais: set[str] | None = None,
        limit: int | None = None,
    ) -> None:
        self._portais = portais or set(self.PORTAIS.keys())
        self._limit = limit

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch published acórdãos from configured portais.

        Returns:
            List of FonteJurisprudencia, empty until ToS compliance is cleared.
        """
        # TODO: Implement HTTP fetching after per-portal ToS compliance check
        logger.info(
            "JurisprudenciaPortaisIngester: GATED on ToS compliance. "
            "Configured portais: %s",
            ", ".join(sorted(self._portais)),
        )
        return []

    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a FonteJurisprudencia into document chunks.

        Args:
            raw: A FonteJurisprudencia instance.

        Returns:
            List of document chunks.
        """
        if not isinstance(raw, FonteJurisprudencia):
            return []
        return chunk_fonte(raw)

    @staticmethod
    def _make_fonte(
        tribunal: str,
        numero: str,
        ementa: str,
        texto: str | None,
        url: str,
        relator: str | None = None,
    ) -> FonteJurisprudencia:
        """Build a FonteJurisprudencia for a published acórdão.

        Args:
            tribunal: Court identifier (e.g., "TJSP").
            numero: Case number or acórdão identifier.
            ementa: Decision summary (ementa).
            texto: Full text of the decision, if available.
            url: Source URL on the tribunal portal.
            relator: Reporting justice name.

        Returns:
            FonteJurisprudencia with tipo=ACORDAO_PUBLICADO and hierarquia=5.
        """
        source_id = f"acordao_publicado_{tribunal.lower()}_{numero[:40]}"
        return FonteJurisprudencia(
            id=source_id,
            tribunal=tribunal,
            tipo=TipoFonte.ACORDAO_PUBLICADO,
            numero=numero,
            ementa=ementa,
            texto_integral=texto,
            relator=relator,
            situacao="vigente",
            hierarquia=5,
            source_url=url,
            source_publisher=tribunal,
        )
