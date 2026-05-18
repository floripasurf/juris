"""HTTP fetcher for STF Repercussão Geral themes.

Fetches themes with settled thesis from the STF public portal.
Falls back gracefully to an empty list if the API is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)


class STFRepercussaoGeralFetcher(CorpusIngester):
    """Fetches STF Repercussão Geral themes from the public portal.

    Args:
        base_url: Base URL for the STF RG API.
        timeout: HTTP request timeout in seconds.
        page_size: Number of themes per page.
    """

    BASE_URL = "https://portal.stf.jus.br/jurisprudenciaRepercussao"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 30,
        page_size: int = 100,
    ) -> None:
        self._base_url = base_url or self.BASE_URL
        self._timeout = timeout
        self._page_size = page_size

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch RG themes with settled thesis.

        Returns:
            List of FonteJurisprudencia for themes with TESE_FIRMADA.
        """
        themes = self._fetch_paginated()
        decided = [
            t for t in themes
            if t.get("tese") and t.get("situacao", "").upper() in ("TESE_FIRMADA", "TRANSITADO")
        ]
        fontes: list[FonteJurisprudencia] = []
        for item in decided:
            fonte = self._parse_item(item)
            if fonte:
                fontes.append(fonte)
        logger.info("Fetched %d STF RG themes (from %d total)", len(fontes), len(themes))
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
        """Parse a single theme into FonteJurisprudencia.

        Args:
            item: Theme dictionary from the API.

        Returns:
            FonteJurisprudencia or None if the theme has no thesis text.
        """
        numero = item.get("numero", "")
        tese = item.get("tese", "")
        if not tese:
            return None

        source_id = f"re_stf_STF_{numero}"
        return FonteJurisprudencia(
            id=source_id,
            tribunal="STF",
            tipo=TipoFonte.RE_STF,
            numero=str(numero),
            ementa=tese,
            texto_integral=item.get("descricao"),
            relator=item.get("relator"),
            temas=item.get("temas", [item.get("area", "")]) if item.get("area") or item.get("temas") else [],
            base_legal=item.get("base_legal", []),
            situacao=item.get("situacao", "tese_firmada").lower(),
            hierarquia=2,
        )

    def _fetch_paginated(self) -> list[dict[str, Any]]:
        """Fetch all themes via paginated API calls.

        Returns:
            List of raw theme dictionaries.
        """
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available for STF RG fetch")
            return []

        all_themes: list[dict[str, Any]] = []
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
                all_themes.extend(items)
                if len(items) < self._page_size:
                    break
                offset += self._page_size
        except Exception:
            logger.warning(
                "Could not fetch STF RG themes from %s. "
                "Use SeedLoader with local JSON files instead.",
                self._base_url,
            )

        return all_themes
