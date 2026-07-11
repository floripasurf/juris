"""EJEF search channel for TJMG."""

from __future__ import annotations

import re

import httpx

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem, ResultadoBusca
from juris.busca.retry import busca_circuit_breaker
from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text

logger = get_logger(__name__)

_TIMEOUT = 20.0
_TRIBUNAL_ID = "tjmg"

_EJEF_URL = "https://www4.tjmg.jus.br/juridico/sf/proc_complemento.jsp"

# CNJ number pattern: NNNNNNN-DD.AAAA.J.TR.OOOO
_CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


class EjefChannel(SearchChannel):
    """Search channel for EJEF (TJMG)."""

    @property
    def channel_name(self) -> FonteOrigem:
        """Return the channel's FonteOrigem identifier."""
        return FonteOrigem.EJEF

    def supported_tribunais(self) -> list[str]:
        """Return list of tribunal IDs this channel can query."""
        return [_TRIBUNAL_ID]

    async def search_by_name(
        self, tribunal_id: str, nome: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by party name on EJEF/TJMG."""
        if tribunal_id != _TRIBUNAL_ID:
            return []
        return await self._search({"nomeParte": nome}, tribunal_id, max_results)

    async def search_by_cpf(
        self, tribunal_id: str, cpf: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by CPF/CNPJ on EJEF/TJMG."""
        if tribunal_id != _TRIBUNAL_ID:
            return []
        return await self._search({"docParte": cpf}, tribunal_id, max_results)

    async def search_by_oab(
        self, tribunal_id: str, oab: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by OAB registration number. Not supported on EJEF."""
        logger.debug("oab_search_not_supported", channel="ejef", tribunal_id=tribunal_id)
        return []

    async def _search(
        self,
        form_data: dict[str, str],
        tribunal_id: str,
        max_results: int,
    ) -> list[ResultadoBusca]:
        """POST search to EJEF and parse HTML response."""
        try:
            busca_circuit_breaker.check(tribunal_id)
        except RuntimeError:
            logger.warning("circuit_open", tribunal_id=tribunal_id)
            return []

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _EJEF_URL,
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()

            busca_circuit_breaker.record_success(tribunal_id)
            return self._parse_html(resp.text, max_results)

        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError) as exc:
            busca_circuit_breaker.record_failure(tribunal_id)
            logger.warning("ejef_request_failed", tribunal_id=tribunal_id, error=safe_error_text(exc))
            return []

    def _parse_html(self, html: str, max_results: int) -> list[ResultadoBusca]:
        """Parse EJEF HTML table into ResultadoBusca list."""
        results: list[ResultadoBusca] = []

        # Extract table rows — EJEF returns an HTML table with case info
        row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        cell_re = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
        tag_re = re.compile(r"<[^>]+>")

        rows = row_re.findall(html)
        seen: set[str] = set()

        for row in rows:
            cells = cell_re.findall(row)
            if len(cells) < 2:
                continue

            # Clean HTML tags from cell content
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

            # Extract fields from cells (order varies, use heuristics)
            classe = cleaned[1] if len(cleaned) > 1 else ""
            data = ""
            data_re_local = re.compile(r"\d{2}/\d{2}/\d{4}")
            for cell_text in cleaned:
                m = data_re_local.search(cell_text)
                if m:
                    data = m.group()
                    break

            results.append(
                ResultadoBusca(
                    numero_cnj=cnj_match,
                    tribunal=_TRIBUNAL_ID.upper(),
                    fonte=FonteOrigem.EJEF,
                    classe=classe,
                    assunto="",
                    orgao_julgador="",
                    data_ajuizamento=data,
                    grau="1",
                    ultima_atualizacao="",
                )
            )

        logger.info("ejef_results", count=len(results))
        return results
