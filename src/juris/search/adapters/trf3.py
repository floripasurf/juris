"""TRF3 (Tribunal Regional Federal da 3ª Região) search adapter."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from juris.search.adapters import register_adapter
from juris.search.adapters.base import SearchAdapter
from juris.search.models import QueryType, SearchQuery, SearchResult
from juris.search.utils import clean_ementa, normalize_cnj, parse_br_date

logger = logging.getLogger(__name__)

_PORTAL_URL = "https://web.trf3.jus.br/base-textual/Home/ListaResumida"
_URL_PREFIX = "https://web.trf3.jus.br"

_CNJ_PATTERN_RE = __import__("re").compile(
    r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"
)
_RELATOR_PREFIX = "Des. Fed. "


@register_adapter
class TRF3Adapter(SearchAdapter):
    """Adapter for TRF3 Base Textual HTML search portal.

    Parses the ``table#tabelaResultado`` table produced by the
    ``/base-textual/Home/ListaResumida`` endpoint.
    """

    court_code: str = "trf3"
    portal_url: str = _PORTAL_URL
    rate_limit_seconds: float = 2.0
    supported_query_types: set[QueryType] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search TRF3 jurisprudência portal.

        Args:
            query: Structured search parameters.

        Returns:
            List of :class:`~juris.search.models.SearchResult`, possibly empty.
        """
        if not self.supports(query.query_type):
            return []
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": self.user_agent},
                timeout=30.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(
                    self.portal_url, params={"strPesq": query.value}
                )
                resp.raise_for_status()
            return self._parse(resp.text, query)
        except Exception:
            logger.warning("TRF3 search failed", exc_info=True)
            return []

    def _parse(self, html: str, query: SearchQuery) -> list[SearchResult]:
        """Parse HTML table response from TRF3 Base Textual portal.

        Targets ``table#tabelaResultado tbody tr`` rows with columns:
        ``td.colProcesso``, ``td.colData``, ``td.colRelator``, ``td.colEmenta``.

        Args:
            html: Raw HTML response text.
            query: Original search query.

        Returns:
            List of parsed search results.
        """
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []

        table = soup.find("table", {"id": "tabelaResultado"})
        if table is None:
            return results

        tbody = table.find("tbody")
        if tbody is None:
            return results

        for row in tbody.find_all("tr"):
            try:
                col_processo = row.find("td", class_="colProcesso")
                col_data = row.find("td", class_="colData")
                col_relator = row.find("td", class_="colRelator")
                col_ementa = row.find("td", class_="colEmenta")

                if col_processo is None:
                    continue

                link = col_processo.find("a")
                if link is None:
                    continue

                # CNJ number is the second line of text inside the <a> tag
                link_text = link.get_text("\n", strip=True)
                lines = [ln.strip() for ln in link_text.splitlines() if ln.strip()]
                cnj_line = next(
                    (ln for ln in lines if _CNJ_PATTERN_RE.search(ln)), None
                )
                case_number = cnj_line if cnj_line else (lines[-1] if lines else "")

                href = link.get("href", "")
                url = (
                    _URL_PREFIX + href
                    if href.startswith("/")
                    else href or self.portal_url
                )

                date_text = col_data.get_text(strip=True) if col_data else None

                relator_raw = col_relator.get_text(strip=True) if col_relator else None
                relator: str | None = None
                if relator_raw:
                    relator = (
                        relator_raw[len(_RELATOR_PREFIX):]
                        if relator_raw.startswith(_RELATOR_PREFIX)
                        else relator_raw
                    )

                ementa_text = (
                    col_ementa.get_text(" ", strip=True) if col_ementa else ""
                )

                results.append(
                    SearchResult(
                        court=self.court_code,
                        case_number=case_number,
                        cnj_number=normalize_cnj(case_number),
                        decision_date=parse_br_date(date_text),
                        relator=relator,
                        classe=None,
                        ementa=clean_ementa(ementa_text),
                        url=url,
                        source_query=query,
                        fetched_at=datetime.now(),
                    )
                )
            except Exception:
                logger.debug("TRF3: failed to parse row", exc_info=True)
                continue

        return results[: query.max_results_per_court]
