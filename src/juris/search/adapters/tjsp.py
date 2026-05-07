"""TJSP (Tribunal de Justiça do Estado de São Paulo) search adapter.

Uses the ESAJ CJSG portal with a 2-step ViewState flow:
1. GET ``/cjsg/consultaCompleta.do`` to obtain the ViewState token + cookies.
2. POST ``/cjsg/resultadoCompleta.do`` with the ViewState and query.
"""

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

_PORTAL_BASE = "https://esaj.tjsp.jus.br"
_CONSULTA_URL = f"{_PORTAL_BASE}/cjsg/consultaCompleta.do"
_RESULTADO_URL = f"{_PORTAL_BASE}/cjsg/resultadoCompleta.do"


@register_adapter
class TJSPAdapter(SearchAdapter):
    """Adapter for TJSP ESAJ CJSG jurisprudência portal.

    Performs a 2-step HTTP flow to obtain the JSF ViewState token before
    submitting the search form, mimicking browser behaviour required by
    the ESAJ platform.
    """

    court_code: str = "tjsp"
    portal_url: str = _PORTAL_BASE
    rate_limit_seconds: float = 3.0
    supported_query_types: set[QueryType] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search TJSP CJSG jurisprudência portal.

        Executes a 2-step GET + POST flow:
        1. Retrieve the search page to capture the ViewState token and session
           cookies.
        2. Submit the search form via POST with the ViewState and query text.

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
                # Step 1: GET search page for ViewState + cookies
                page_resp = await client.get(_CONSULTA_URL)
                page_resp.raise_for_status()
                viewstate = self._extract_viewstate(page_resp.text)

                # Step 2: POST search with ViewState
                form_data = {
                    "dados.buscaInteiroTeor": query.value,
                    "dados.pesquisarComSinonimos": "S",
                    "dados.buscaEm498": "",
                    "javax.faces.ViewState": viewstate or "",
                }
                resp = await client.post(_RESULTADO_URL, data=form_data)
                resp.raise_for_status()

            return self._parse(resp.text, query)
        except Exception:
            logger.warning("TJSP search failed", exc_info=True)
            return []

    def _extract_viewstate(self, html: str) -> str | None:
        """Extract the JSF ViewState hidden input value from an HTML page.

        Args:
            html: Raw HTML of the TJSP search page.

        Returns:
            ViewState token string, or None if not found.
        """
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("input", {"name": "javax.faces.ViewState"})
        if tag and tag.get("value"):
            return str(tag["value"])
        return None

    def _parse(self, html: str, query: SearchQuery) -> list[SearchResult]:
        """Parse HTML results from TJSP CJSG portal.

        Targets ``table#tabelaResultados tbody tr`` rows. Expected columns:
        process link + classe span, relator, órgão julgador, date, ementa.

        Args:
            html: Raw HTML response text.
            query: Original search query.

        Returns:
            List of parsed search results.
        """
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []

        table = soup.find("table", {"id": "tabelaResultados"})
        if table is None:
            return results

        tbody = table.find("tbody")
        if tbody is None:
            return results

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            try:
                first_cell = cells[0]
                link = first_cell.find("a")

                case_number = link.get_text(strip=True) if link else ""
                href = link.get("href", "") if link else ""
                url = _PORTAL_BASE + href if href.startswith("/") else href or self.portal_url

                classe_tag = first_cell.find("span", class_="classeTipoDocumento")
                classe = classe_tag.get_text(strip=True) if classe_tag else None

                relator = cells[1].get_text(strip=True) if len(cells) > 1 else None
                # cells[2] = órgão julgador (not mapped to SearchResult)
                date_text = cells[3].get_text(strip=True) if len(cells) > 3 else None

                ementa_cell = row.find("td", class_="ementaAcordao")
                if ementa_cell is None and len(cells) > 4:
                    ementa_cell = cells[4]
                ementa_text = ementa_cell.get_text(" ", strip=True) if ementa_cell else ""

                results.append(
                    SearchResult(
                        court=self.court_code,
                        case_number=case_number,
                        cnj_number=normalize_cnj(case_number),
                        decision_date=parse_br_date(date_text),
                        relator=relator or None,
                        classe=classe,
                        ementa=clean_ementa(ementa_text),
                        url=url,
                        source_query=query,
                        fetched_at=datetime.now(),
                    )
                )
            except Exception:
                logger.debug("TJSP: failed to parse row", exc_info=True)
                continue

        return results[: query.max_results_per_court]
