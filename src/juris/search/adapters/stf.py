"""STF (Supremo Tribunal Federal) search adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import ClassVar

from juris.search.adapters import register_adapter
from juris.search.adapters.base import SearchAdapter
from juris.search.http import make_portal_client
from juris.search.models import QueryType, SearchQuery, SearchResult
from juris.search.utils import clean_ementa, normalize_cnj, parse_br_date

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://jurisprudencia.stf.jus.br/pages/search"
_URL_PREFIX = "https://portal.stf.jus.br"


@register_adapter
class STFAdapter(SearchAdapter):
    """Adapter for the STF jurisprudência JSON API.

    Queries the STF portal's accordão search endpoint and parses the
    JSON response into :class:`~juris.search.models.SearchResult` objects.
    """

    court_code: ClassVar[str] = "stf"
    portal_url: ClassVar[str] = "https://jurisprudencia.stf.jus.br"
    rate_limit_seconds: ClassVar[float] = 2.0
    supported_query_types: ClassVar[set[QueryType]] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search the STF jurisprudência API.

        Args:
            query: Structured search parameters.

        Returns:
            List of :class:`~juris.search.models.SearchResult`, possibly empty.
        """
        params: dict[str, str | int] = {
            "base": "acordaos",
            "pesquisa_inteiro_teor": "false",
            "sinonimo": "true",
            "plural": "true",
            "radicais": "false",
            "buscaExata": "true",
            "page": 1,
            "pageSize": query.max_results_per_court,
            "queryString": query.value,
            "sort": "_score",
            "sortBy": "desc",
        }

        try:
            async with make_portal_client(self.user_agent) as client:
                response = await client.get(_SEARCH_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            from juris.core.sanitize import safe_error_text

            logger.warning("STF search request failed for query %r: %s", query.value, safe_error_text(exc))
            return []

        results: list[SearchResult] = []
        for item in data.get("result", []):
            try:
                case_number: str = item.get("classeNumero", "")
                classe: str | None = case_number.split()[0] if case_number else None
                raw_url: str = item.get("url", "")
                url: str = _URL_PREFIX + raw_url if raw_url.startswith("/") else raw_url

                result = SearchResult(
                    court=self.court_code,
                    case_number=case_number,
                    cnj_number=normalize_cnj(case_number),
                    decision_date=parse_br_date(item.get("dataJulgamento")),
                    relator=item.get("relator") or None,
                    classe=classe,
                    ementa=clean_ementa(item.get("description", "")),
                    url=url,
                    source_query=query,
                    fetched_at=datetime.now(),
                )
                results.append(result)
            except Exception:
                logger.exception("Failed to parse STF result item: %r", item)

        return results
