"""HTTP fetcher for STF Sumulas and Sumulas Vinculantes.

Fetches publicly available sumulas from the STF portal.
Uses placeholder URLs — real endpoints should be configured via settings.
"""

from __future__ import annotations

import logging
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)


class STFSumulasFetcher(CorpusIngester):
    """Fetches STF sumulas and sumulas vinculantes from the public portal.

    Args:
        base_url: Base URL for the STF portal API.
        tipo: Type of sumula to fetch.
        timeout: HTTP request timeout in seconds.
    """

    BASE_URL = "https://portal.stf.jus.br/api/sumulas"

    def __init__(
        self,
        base_url: str | None = None,
        tipo: TipoFonte = TipoFonte.SUMULA_VINCULANTE,
        timeout: int = 30,
    ) -> None:
        self._base_url = base_url or self.BASE_URL
        self._tipo = tipo
        self._timeout = timeout

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch sumulas from the STF portal.

        Returns:
            List of FonteJurisprudencia objects.
        """
        try:
            import httpx

            url = f"{self._base_url}/listar"
            params = {"tipo": self._tipo.value}
            response = httpx.get(url, params=params, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.warning(
                "Could not fetch STF sumulas from %s. "
                "Use SeedLoader with local JSON files instead.",
                self._base_url,
            )
            return []

        fontes: list[FonteJurisprudencia] = []
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            fonte = self._parse_item(item)
            if fonte:
                fontes.append(fonte)

        logger.info("Fetched %d STF sumulas", len(fontes))
        return fontes

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

    def _parse_item(self, item: dict[str, Any]) -> FonteJurisprudencia | None:
        """Parse a single API response item.

        Args:
            item: JSON dictionary from API response.

        Returns:
            FonteJurisprudencia or None if invalid.
        """
        numero = item.get("numero", "")
        texto = item.get("texto") or item.get("enunciado", "")
        if not texto:
            return None

        hierarquia = 1 if self._tipo == TipoFonte.SUMULA_VINCULANTE else 4
        source_id = f"{self._tipo.value}_STF_{numero}"

        return FonteJurisprudencia(
            id=source_id,
            tribunal="STF",
            tipo=self._tipo,
            numero=str(numero),
            ementa=texto,
            texto_integral=item.get("texto_integral"),
            relator=item.get("relator"),
            temas=item.get("temas", []),
            base_legal=item.get("base_legal", []),
            situacao=item.get("situacao", "vigente"),
            hierarquia=hierarquia,
        )
