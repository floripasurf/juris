"""Ingester for landmark court decisions (acórdãos históricos).

GATED: Requires ToS compliance check per portal before enabling HTTP fetching.
Sources: STF "Decisões Históricas", STJ "Casos Marcantes".
"""

from __future__ import annotations

import logging
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

_SOURCES: dict[str, str] = {
    "STF": "STF Decisões Históricas — https://portal.stf.jus.br/jurisprudencia/",
    "STJ": "STJ Casos Marcantes — https://scon.stj.jus.br/SCON/",
}


class LandmarkCasesIngester(CorpusIngester):
    """Ingests landmark court decisions from STF and STJ public portals.

    tipo: ACORDAO_LANDMARK, hierarquia: 3.
    Rate limit: ≤1 req/2sec, off-peak only.

    GATED: ToS compliance check required before activation.
    See data/tos_compliance_log.md for status per portal.

    Args:
        limit: Maximum number of entries to ingest (None for all).
    """

    SOURCES: dict[str, str] = _SOURCES

    def __init__(self, limit: int | None = None) -> None:
        self._limit = limit

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch landmark decisions from configured portals.

        Returns:
            List of FonteJurisprudencia, empty until ToS compliance is cleared.
        """
        # TODO: Implement HTTP fetching after ToS compliance check per portal
        logger.info(
            "LandmarkCasesIngester: GATED on ToS compliance. "
            "Configured sources: %s",
            ", ".join(self.SOURCES),
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
        """Build a FonteJurisprudencia for a landmark decision.

        Args:
            tribunal: Court identifier (e.g., "STF", "STJ").
            numero: Case number or decision identifier.
            ementa: Decision summary (ementa).
            texto: Full decision text, if available.
            url: Source URL on the court portal.
            relator: Reporting justice name.

        Returns:
            FonteJurisprudencia with tipo=ACORDAO_LANDMARK and hierarquia=3.
        """
        source_id = f"acordao_landmark_{tribunal.lower()}_{numero[:40]}"
        return FonteJurisprudencia(
            id=source_id,
            tribunal=tribunal,
            tipo=TipoFonte.ACORDAO_LANDMARK,
            numero=numero,
            ementa=ementa,
            texto_integral=texto,
            relator=relator,
            situacao="vigente",
            hierarquia=3,
            source_url=url,
            source_publisher=tribunal,
        )
