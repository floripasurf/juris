"""STJ (Superior Tribunal de Justiça) search adapter."""

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

_SEARCH_URL = "https://scon.stj.jus.br/SCON/pesquisar.jsp"
_URL_PREFIX = "https://scon.stj.jus.br"
_RELATOR_PREFIXES = ("Ministro ", "Ministra ")


def _strip_relator_prefix(text: str) -> str:
    """Remove 'Ministro '/'Ministra ' prefix and title-case the name.

    Args:
        text: Raw relator cell text.

    Returns:
        Cleaned relator name string.
    """
    stripped = text.strip()
    for prefix in _RELATOR_PREFIXES:
        if stripped.upper().startswith(prefix.upper()):
            return stripped[len(prefix) :].strip()
    return stripped


@register_adapter
class STJAdapter(SearchAdapter):
    """Adapter for the STJ SCON jurisprudência HTML portal.

    Sends a GET request to SCON and parses the HTML response using
    BeautifulSoup to extract acordão results.
    """

    court_code: ClassVar[str] = "stj"
    portal_url: ClassVar[str] = "https://scon.stj.jus.br"
    rate_limit_seconds: ClassVar[float] = 2.0
    supported_query_types: ClassVar[set[QueryType]] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search the STJ SCON HTML portal.

        Args:
            query: Structured search parameters.

        Returns:
            List of :class:`~juris.search.models.SearchResult`, possibly empty.
        """
        params: dict[str, str] = {
            "livre": query.value,
            "b": "ACOR",
            "thesaurus": "JURIDICO",
            "p": "true",
        }

        try:
            async with make_portal_client(self.user_agent) as client:
                response = await client.get(_SEARCH_URL, params=params)
                response.raise_for_status()
                html = response.text
        except Exception:
            logger.exception("STJ search request failed for query %r", query.value)
            return []

        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            divs = soup.select("div.divResult")
        except Exception:
            logger.exception("STJ HTML parsing failed")
            return []

        for div in divs:
            try:
                # Process number: first td.dadoPesquisa containing an <a>
                process_link = div.select_one("td.dadoPesquisa > a")
                case_number = process_link.get_text(strip=True) if process_link else ""
                raw_href = str(process_link.get("href") or "") if process_link else ""
                url = _URL_PREFIX + raw_href if raw_href.startswith("/") else raw_href

                # All data rows
                rows = div.select("tr")

                relator: str | None = None
                date_text: str | None = None

                for row in rows:
                    label_td = row.find("td", class_="labelPesquisa")
                    data_td = row.find("td", class_="dadoPesquisa")
                    if not label_td or not data_td:
                        continue

                    label = label_td.get_text(strip=True)
                    value = data_td.get_text(strip=True)

                    if "Relator" in label:
                        relator = _strip_relator_prefix(value) or None
                    elif "Data do Julgamento" in label:
                        date_text = value

                # Ementa
                ementa_div = div.select_one("div.docTexto")
                raw_ementa = ementa_div.get_text(separator=" ") if ementa_div else ""
                ementa = clean_ementa(raw_ementa)

                result = SearchResult(
                    court=self.court_code,
                    case_number=case_number,
                    cnj_number=normalize_cnj(case_number),
                    decision_date=parse_br_date(date_text),
                    relator=relator,
                    classe=case_number.split()[0] if case_number else None,
                    ementa=ementa,
                    url=url,
                    source_query=query,
                    fetched_at=datetime.now(),
                )
                results.append(result)
            except Exception:
                logger.exception("Failed to parse STJ result div")

        return results
