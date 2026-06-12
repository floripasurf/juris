"""TST (Tribunal Superior do Trabalho) search adapter.

Portal discovery (validated 2026-06-12):
    The public SPA at https://jurisprudencia.tst.jus.br loads its API base
    from /config.json -> "base_url": https://jurisprudencia-backend2.tst.jus.br.
    Search is a POST to /rest/pesquisa-textual/{start}/{size} where ``start``
    is 1-based. The body mirrors the SPA's advanced-search form; the ``tipos``
    array MUST be non-empty or the backend ignores all filters and returns
    the whole corpus. ``e`` carries the all-words query text.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, ClassVar

from juris.search.adapters import register_adapter
from juris.search.adapters.base import SearchAdapter
from juris.search.http import make_portal_client
from juris.search.models import QueryType, SearchQuery, SearchResult
from juris.search.utils import clean_ementa, normalize_cnj, parse_br_date

logger = logging.getLogger(__name__)

_BACKEND_URL = "https://jurisprudencia-backend2.tst.jus.br/rest/pesquisa-textual"

_TIPO_ACORDAO = {
    "codigo": "ACORDAO",
    "value": "acordaos",
    "codMin": "",
    "checked": True,
    "label": "Acórdãos",
    "qtdRegistros": 0,
}


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

    Queries the TST pesquisa-textual backend and parses the JSON response
    into :class:`~juris.search.models.SearchResult` objects.
    """

    court_code: ClassVar[str] = "tst"
    portal_url: ClassVar[str] = "https://jurisprudencia.tst.jus.br"
    rate_limit_seconds: ClassVar[float] = 2.0
    supported_query_types: ClassVar[set[QueryType]] = {"tema"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Search the TST jurisprudência JSON API.

        Args:
            query: Structured search parameters.

        Returns:
            List of :class:`~juris.search.models.SearchResult`, possibly empty.
        """
        url = f"{_BACKEND_URL}/1/{query.max_results_per_court}"
        body: dict[str, Any] = {
            "e": query.value,
            "ou": "",
            "termoExato": "",
            "naoContem": "",
            "ementa": "",
            "dispositivo": "",
            "tipos": [_TIPO_ACORDAO],
            "orgaosJudicantes": [],
            "ministros": [],
            "convocados": [],
            "classesProcessuais": [],
            "indicadores": [],
            "assuntos": [],
        }

        try:
            async with make_portal_client(self.user_agent) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("TST search request failed for query %r", query.value)
            return []

        results: list[SearchResult] = []
        for wrapper in data.get("registros", []):
            item = wrapper.get("registro", {}) if isinstance(wrapper, dict) else {}
            try:
                numero_processo: str = item.get("numFormatado") or ""
                # numFormatado looks like "RRAg - 2093-21.2017.5.09.0015";
                # the sequential may come without leading zeros, so pad to 7.
                cnj_part = numero_processo.split(" - ", 1)[-1] if numero_processo else ""
                m = re.match(r"^(\d{1,7})-(\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})$", cnj_part)
                if m:
                    cnj_part = f"{m.group(1).zfill(7)}-{m.group(2)}"
                classe = _extract_classe(numero_processo)
                doc_id: str = str(item.get("id") or "")
                url_doc = f"{self.portal_url}/#/detalhe-documento/{doc_id}" if doc_id else self.portal_url

                result = SearchResult(
                    court=self.court_code,
                    case_number=numero_processo,
                    cnj_number=normalize_cnj(cnj_part),
                    decision_date=parse_br_date(item.get("dtaJulgamento")),
                    relator=item.get("nomRelator") or None,
                    classe=classe,
                    ementa=clean_ementa(item.get("ementa") or item.get("txtEmentaHighlight") or ""),
                    url=url_doc,
                    source_query=query,
                    fetched_at=datetime.now(),
                )
                results.append(result)
            except Exception:
                logger.exception("Failed to parse TST result item: %r", item)

        return results
