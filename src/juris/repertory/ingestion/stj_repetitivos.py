"""HTTP fetcher for STJ Recursos Especiais Repetitivos.

Fetches repetitive themes from the STJ public portal.
Uses placeholder URLs — real endpoints should be configured via settings.
"""

from __future__ import annotations

import logging
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)


class STJRepetitivosFetcher(CorpusIngester):
    """Fetches STJ repetitive themes from the public portal.

    Args:
        base_url: Base URL for the STJ API.
        timeout: HTTP request timeout in seconds.
    """

    BASE_URL = "https://processo.stj.jus.br/repetitivos/temas_repetitivos"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 30,
        page_size: int = 100,
        situacoes: tuple[str, ...] = ("AFETADO", "TRANSITADO"),
    ) -> None:
        self._base_url = base_url or self.BASE_URL
        self._timeout = timeout
        self._page_size = page_size
        self._situacoes = tuple(s.upper() for s in situacoes)

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch repetitive themes from STJ portal.

        Returns:
            List of FonteJurisprudencia objects.
        """
        items = self._fetch_paginated()
        fontes: list[FonteJurisprudencia] = []
        for item in items:
            situacao = (item.get("situacao") or "").upper()
            if self._situacoes and situacao not in self._situacoes:
                continue
            fonte = self._parse_item(item)
            if fonte:
                fontes.append(fonte)

        logger.info("Fetched %d STJ repetitive themes (from %d total)", len(fontes), len(items))
        return fontes

    def _fetch_paginated(self) -> list[dict[str, Any]]:
        """Fetch all themes via paginated API calls.

        Returns:
            List of raw theme dictionaries.
        """
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available for STJ repetitivos fetch")
            return []

        all_items: list[dict[str, Any]] = []
        offset = 0
        try:
            while True:
                url = f"{self._base_url}/listar"
                params = {"offset": offset, "limit": self._page_size}
                response = httpx.get(url, params=params, timeout=self._timeout)
                response.raise_for_status()
                data = response.json()
                items = data if isinstance(data, list) else data.get("temas", data.get("items", []))
                if not items:
                    break
                all_items.extend(items)
                if len(items) < self._page_size:
                    break
                offset += self._page_size
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not fetch STJ repetitivos from %s. "
                "Use SeedLoader with local JSON files instead.",
                self._base_url,
            )

        return all_items

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
        tese = item.get("tese") or item.get("descricao", "")
        if not tese:
            return None

        source_id = f"resp_repetitivo_STJ_{numero}"

        return FonteJurisprudencia(
            id=source_id,
            tribunal="STJ",
            tipo=TipoFonte.RESP_REPETITIVO,
            numero=str(numero),
            ementa=tese,
            texto_integral=item.get("texto_integral"),
            relator=item.get("relator"),
            temas=item.get("temas", [item.get("area", "")]) if item.get("area") or item.get("temas") else [],
            base_legal=item.get("base_legal", []),
            situacao=item.get("situacao", "transitado"),
            hierarquia=3,
        )
