"""TST (Tribunal Superior do Trabalho) search adapter."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from juris.search.adapters import register_adapter
from juris.search.adapters.base import SearchAdapter
from juris.search.models import QueryType, SearchQuery, SearchResult
from juris.search.utils import clean_ementa, normalize_cnj, parse_br_date

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://jurisprudencia.tst.jus.br/rest/documentos/acordao"


def _extract_classe(numero_processo: str) -> str | None:
    """Extract the classe abbreviation from a TST process number.

    For example, "RR-10014-28.2019.5.03.0097" -> "RR".

    Args:
        numero_processo: Raw process number string.

    Returns:
        Classe string or None if the format is unrecognised.
    """
    if not numero_processo:
        return None
    part = numero_processo.split("-")[0].strip()
    return part if part else None


@register_adapter
class TSTAdapter(SearchAdapter):
    """Adapter for the TST jurisprudência JSON API.

    Queries the TST acordão search endpoint and parses the JSON response
    into :class:`~juris.search.models.SearchResult` objects.
    """

    court_code: str = "tst"
    portal_url: str = "https://jurisprudencia.tst.jus.br"
    rate_limit_seconds: float = 2.0
    supported_query_types: set[QueryType] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search the TST jurisprudência JSON API.

        Args:
            query: Structured search parameters.

        Returns:
            List of :class:`~juris.search.models.SearchResult`, possibly empty.
        """
        params: dict[str, str | int] = {
            "query": query.value,
            "pageSize": query.max_results_per_court,
            "page": 1,
        }

        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": self.user_agent},
                timeout=30.0,
            ) as client:
                response = await client.get(_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("TST search request failed for query %r", query.value)
            return []

        results: list[SearchResult] = []
        for item in data.get("items", []):
            try:
                numero_processo: str = item.get("numeroProcesso", "")
                classe = _extract_classe(numero_processo)

                result = SearchResult(
                    court=self.court_code,
                    case_number=numero_processo,
                    cnj_number=normalize_cnj(numero_processo),
                    decision_date=parse_br_date(item.get("dataJulgamento")),
                    relator=item.get("relator") or None,
                    classe=classe,
                    ementa=clean_ementa(item.get("ementa", "")),
                    url=item.get("url", ""),
                    source_query=query,
                    fetched_at=datetime.now(),
                )
                results.append(result)
            except Exception:
                logger.exception("Failed to parse TST result item: %r", item)

        return results
