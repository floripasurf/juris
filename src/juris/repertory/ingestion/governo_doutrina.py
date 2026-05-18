"""Ingester for government-published legal doctrine (domínio público).

GATED: HTTP fetching not yet implemented — skeleton only.
Sources: MJSP, STF Memória, CNJ Edições, Senado Editora, IPEA.
"""

from __future__ import annotations

import logging
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

_SOURCES: dict[str, str] = {
    "MJSP": "Ministério da Justiça e Segurança Pública",
    "STF_MEMORIA": "STF Memória — publicações históricas",
    "CNJ_EDICOES": "CNJ Edições — publicações técnicas",
    "SENADO_EDITORA": "Senado Federal Editora",
    "IPEA": "Instituto de Pesquisa Econômica Aplicada",
}


class GovernoDoutrinaIngester(CorpusIngester):
    """Ingests government-published legal doctrine from public sources.

    All publications are in the public domain (governo federal).
    tipo: DOUTRINA_PD, hierarquia: 6.

    Args:
        limit: Maximum number of entries to ingest (None for all).
    """

    SOURCES: dict[str, str] = _SOURCES

    def __init__(self, limit: int | None = None) -> None:
        self._limit = limit

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch government doctrine publications.

        Returns:
            List of FonteJurisprudencia, empty until HTTP fetching is implemented.
        """
        # TODO: Implement HTTP fetching per source
        logger.info(
            "GovernoDoutrinaIngester: HTTP fetching not yet implemented. "
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
        source_key: str,
        numero: str,
        ementa: str,
        texto: str | None,
        url: str,
    ) -> FonteJurisprudencia:
        """Build a FonteJurisprudencia for a government doctrine document.

        Args:
            source_key: Key from SOURCES dict (e.g., "MJSP").
            numero: Document identifier or title slug.
            ementa: Short description of the publication.
            texto: Full text, if available.
            url: Source URL.

        Returns:
            FonteJurisprudencia with tipo=DOUTRINA_PD and hierarquia=6.
        """
        source_id = f"doutrina_pd_{source_key.lower()}_{numero[:40]}"
        return FonteJurisprudencia(
            id=source_id,
            tribunal=source_key,
            tipo=TipoFonte.DOUTRINA_PD,
            numero=numero,
            ementa=ementa,
            texto_integral=texto,
            situacao="vigente",
            hierarquia=6,
            source_url=url,
            source_publisher=_SOURCES.get(source_key, source_key),
            legal_basis="GOVERNMENT_PUBLICATION",
        )
