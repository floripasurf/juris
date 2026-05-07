"""PROJUDI search channel for TJPR."""

from __future__ import annotations

import re

import httpx

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem, ResultadoBusca
from juris.busca.retry import busca_circuit_breaker
from juris.core.observability import get_logger

logger = get_logger(__name__)

_TIMEOUT = 20.0
_TRIBUNAL_ID = "tjpr"

_PROJUDI_BASE = "https://projudi.tjpr.jus.br/projudi/"
_PROJUDI_SEARCH = _PROJUDI_BASE + "listasProcessos.do"

# CNJ number pattern: NNNNNNN-DD.AAAA.J.TR.OOOO
_CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


class ProjudiChannel(SearchChannel):
    """Search channel for PROJUDI (TJPR)."""

    @property
    def channel_name(self) -> FonteOrigem:
        """Return the channel's FonteOrigem identifier."""
        return FonteOrigem.PROJUDI

    def supported_tribunais(self) -> list[str]:
        """Return list of tribunal IDs this channel can query."""
        return [_TRIBUNAL_ID]

    async def search_by_name(
        self, tribunal_id: str, nome: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by party name on PROJUDI/TJPR."""
        if tribunal_id != _TRIBUNAL_ID:
            return []
        return await self._search({"nomeParte": nome}, tribunal_id, max_results)

    async def search_by_cpf(
        self, tribunal_id: str, cpf: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by CPF/CNPJ on PROJUDI/TJPR."""
        if tribunal_id != _TRIBUNAL_ID:
            return []
        return await self._search({"docParte": cpf}, tribunal_id, max_results)

    async def search_by_oab(
        self, tribunal_id: str, oab: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by OAB registration number. Not supported on PROJUDI."""
        logger.debug("oab_search_not_supported", channel="projudi", tribunal_id=tribunal_id)
        return []

    async def _search(
        self,
        form_data: dict[str, str],
        tribunal_id: str,
        max_results: int,
    ) -> list[ResultadoBusca]:
        """Perform session-based search on PROJUDI.

        PROJUDI requires a session cookie obtained via an initial GET
        before POSTing the search form.
        """
        try:
            busca_circuit_breaker.check(tribunal_id)
        except RuntimeError:
            logger.warning("circuit_open", tribunal_id=tribunal_id)
            return []

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, follow_redirects=True
            ) as client:
                # Step 1: GET to establish session
                session_resp = await client.get(_PROJUDI_BASE)
                session_resp.raise_for_status()

                # Step 2: POST search form with session cookies
                resp = await client.post(
                    _PROJUDI_SEARCH,
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()

            busca_circuit_breaker.record_success(tribunal_id)
            return self._parse_html(resp.text, max_results)

        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError) as exc:
            busca_circuit_breaker.record_failure(tribunal_id)
            logger.warning("projudi_request_failed", tribunal_id=tribunal_id, error=str(exc))
            return []

    def _parse_html(self, html: str, max_results: int) -> list[ResultadoBusca]:
        """Parse PROJUDI HTML table into ResultadoBusca list."""
        results: list[ResultadoBusca] = []

        row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        cell_re = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
        tag_re = re.compile(r"<[^>]+>")
        date_re = re.compile(r"\d{2}/\d{2}/\d{4}")

        rows = row_re.findall(html)
        seen: set[str] = set()

        for row in rows:
            cells = cell_re.findall(row)
            if len(cells) < 2:
                continue

            cleaned = [tag_re.sub("", c).strip() for c in cells]

            # Find CNJ number in any cell
            cnj_match: str | None = None
            for cell_text in cleaned:
                match = _CNJ_RE.search(cell_text)
                if match:
                    cnj_match = match.group()
                    break

            if not cnj_match or cnj_match in seen:
                continue
            seen.add(cnj_match)

            if len(results) >= max_results:
                break

            # Extract classe and data from remaining cells
            classe = ""
            data_ajuizamento = ""
            orgao = ""

            for cell_text in cleaned:
                if _CNJ_RE.search(cell_text):
                    continue
                dm = date_re.search(cell_text)
                if dm and not data_ajuizamento:
                    data_ajuizamento = dm.group()
                elif not classe and len(cell_text) > 3:
                    classe = cell_text
                elif not orgao and "vara" in cell_text.lower():
                    orgao = cell_text

            results.append(
                ResultadoBusca(
                    numero_cnj=cnj_match,
                    tribunal=_TRIBUNAL_ID.upper(),
                    fonte=FonteOrigem.PROJUDI,
                    classe=classe,
                    assunto="",
                    orgao_julgador=orgao,
                    data_ajuizamento=data_ajuizamento,
                    grau="1",
                    ultima_atualizacao="",
                )
            )

        logger.info("projudi_results", count=len(results))
        return results
