"""TRF6 (Tribunal Regional Federal da 6ª Região) search adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import ClassVar

from bs4 import BeautifulSoup

from juris.search.adapters import register_adapter
from juris.search.adapters.base import SearchAdapter
from juris.search.http import make_portal_client
from juris.search.models import QueryType, SearchQuery, SearchResult
from juris.search.utils import clean_ementa, normalize_cnj, parse_br_date

logger = logging.getLogger(__name__)

_PORTAL_URL = "https://trf6.jus.br/jurisprudencia/pesquisa"
_URL_PREFIX = "https://trf6.jus.br"

_CNJ_PATTERN_RE = __import__("re").compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


@register_adapter
class TRF6Adapter(SearchAdapter):
    """Adapter for TRF6 jurisprudência HTML search portal."""

    court_code: ClassVar[str] = "trf6"
    portal_url: ClassVar[str] = _PORTAL_URL
    rate_limit_seconds: ClassVar[float] = 2.0
    supported_query_types: ClassVar[set[QueryType]] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search TRF6 jurisprudência portal.

        Args:
            query: Structured search parameters.

        Returns:
            List of :class:`~juris.search.models.SearchResult`, possibly empty.
        """
        if not self.supports(query.query_type):
            return []
        try:
            async with make_portal_client(self.user_agent, follow_redirects=True) as client:
                resp = await client.get(self.portal_url, params={"livre": query.value})
                resp.raise_for_status()
            return self._parse(resp.text, query)
        except Exception:
            logger.warning("TRF6 search failed", exc_info=True)
            return []

    def _parse(self, html: str, query: SearchQuery) -> list[SearchResult]:
        """Parse HTML table response from TRF6 portal.

        Args:
            html: Raw HTML response text.
            query: Original search query.

        Returns:
            List of parsed search results.
        """
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []

        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                try:
                    first_cell = cells[0]
                    link = first_cell.find("a")
                    cell_text = first_cell.get_text(" ", strip=True)

                    cnj_match = _CNJ_PATTERN_RE.search(cell_text)
                    case_number = cnj_match.group(0) if cnj_match else cell_text[:60]

                    href = str(link["href"]) if link and link.get("href") else ""
                    url = _URL_PREFIX + href if href.startswith("/") else href or self.portal_url

                    date_text = cells[1].get_text(strip=True) if len(cells) > 1 else None
                    relator = cells[2].get_text(strip=True) if len(cells) > 2 else None
                    ementa_text = cells[3].get_text(" ", strip=True) if len(cells) > 3 else ""

                    results.append(
                        SearchResult(
                            court=self.court_code,
                            case_number=case_number,
                            cnj_number=normalize_cnj(case_number),
                            decision_date=parse_br_date(date_text),
                            relator=relator or None,
                            classe=None,
                            ementa=clean_ementa(ementa_text),
                            url=url,
                            source_query=query,
                            fetched_at=datetime.now(),
                        )
                    )
                except Exception:
                    logger.debug("TRF6: failed to parse row", exc_info=True)
                    continue

        return results[: query.max_results_per_court]
