"""eProc search channel for TRF4, TJRS, TJSC, TJTO."""

from __future__ import annotations

import re
from typing import Any

import httpx

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem, ResultadoBusca
from juris.busca.retry import busca_circuit_breaker
from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text

logger = get_logger(__name__)

_TIMEOUT = 20.0

# CNJ number pattern: NNNNNNN-DD.AAAA.J.TR.OOOO
_CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")

_EPROC_CONFIG: dict[str, dict[str, str]] = {
    "trf4": {
        "type": "json",
        "base": "https://consulta-processual.trf4.jus.br/consulta-processual",
        "search_path": "/api/processos",
    },
    "tjrs": {
        "type": "html",
        "base": "https://www.tjrs.jus.br",
        "search_path": "/site_php/consulta/consultaProcesso.php",
    },
    "tjsc": {
        "type": "html",
        "base": "https://eproc1g.tjsc.jus.br",
        "search_path": "/eproc/externo_controlador.php",
    },
    "tjto": {
        "type": "html",
        "base": "https://eproc1.tjto.jus.br",
        "search_path": "/eprocV2_1grau/externo_controlador.php",
    },
}


class EprocChannel(SearchChannel):
    """Search channel for eProc-based tribunals (TRF4, TJRS, TJSC, TJTO)."""

    @property
    def channel_name(self) -> FonteOrigem:
        """Return the channel's FonteOrigem identifier."""
        return FonteOrigem.EPROC

    def supported_tribunais(self) -> list[str]:
        """Return list of tribunal IDs this channel can query."""
        return list(_EPROC_CONFIG.keys())

    async def search_by_name(
        self, tribunal_id: str, nome: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by party name across eProc tribunals."""
        config = _EPROC_CONFIG.get(tribunal_id)
        if not config:
            logger.warning("unsupported_tribunal", tribunal_id=tribunal_id)
            return []

        if config["type"] == "json":
            return await self._search_trf4_json(
                config, tribunal_id, params={"nome_parte": nome}, max_results=max_results
            )
        return await self._search_html(
            config, tribunal_id, form_data={"nome_parte": nome}, max_results=max_results
        )

    async def search_by_cpf(
        self, tribunal_id: str, cpf: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by CPF/CNPJ document number."""
        config = _EPROC_CONFIG.get(tribunal_id)
        if not config:
            logger.warning("unsupported_tribunal", tribunal_id=tribunal_id)
            return []

        if config["type"] == "json":
            return await self._search_trf4_json(
                config, tribunal_id, params={"cpf_parte": cpf}, max_results=max_results
            )
        return await self._search_html(
            config, tribunal_id, form_data={"doc_parte": cpf}, max_results=max_results
        )

    async def search_by_oab(
        self, tribunal_id: str, oab: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by OAB registration number. Not supported on eProc."""
        logger.debug("oab_search_not_supported", channel="eproc", tribunal_id=tribunal_id)
        return []

    # ---- TRF4 JSON API ----

    async def _search_trf4_json(
        self,
        config: dict[str, str],
        tribunal_id: str,
        params: dict[str, str],
        max_results: int,
    ) -> list[ResultadoBusca]:
        """Query TRF4 JSON API and parse results."""
        url = config["base"] + config["search_path"]
        try:
            busca_circuit_breaker.check(tribunal_id)
        except RuntimeError:
            logger.warning("circuit_open", tribunal_id=tribunal_id)
            return []

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()

            busca_circuit_breaker.record_success(tribunal_id)
            data = resp.json()
            return self._parse_trf4_json(data, tribunal_id, max_results)

        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError) as exc:
            busca_circuit_breaker.record_failure(tribunal_id)
            logger.warning("eproc_request_failed", tribunal_id=tribunal_id, error=safe_error_text(exc))
            return []

    def _parse_trf4_json(
        self, data: Any, tribunal_id: str, max_results: int
    ) -> list[ResultadoBusca]:
        """Parse TRF4 JSON response into ResultadoBusca list."""
        results: list[ResultadoBusca] = []
        items = data if isinstance(data, list) else data.get("processos", data.get("items", []))

        for item in items[:max_results]:
            if not isinstance(item, dict):
                continue
            numero = item.get("numeroProcesso", item.get("numero", ""))
            if not numero:
                continue
            results.append(
                ResultadoBusca(
                    numero_cnj=str(numero).strip(),
                    tribunal=tribunal_id.upper(),
                    fonte=FonteOrigem.EPROC,
                    classe=str(item.get("classeProcessual") or item.get("classe") or ""),
                    assunto=item.get("assunto", ""),
                    orgao_julgador=str(item.get("orgaoJulgador") or item.get("vara") or ""),
                    data_ajuizamento=str(item.get("dataAjuizamento") or item.get("dataInicio") or ""),
                    grau=item.get("grau", "1"),
                    ultima_atualizacao=item.get("ultimaAtualizacao", ""),
                    polo_ativo=_extract_polo(item, "poloAtivo"),
                    polo_passivo=_extract_polo(item, "poloPassivo"),
                    raw=item,
                )
            )

        logger.info("eproc_trf4_results", tribunal_id=tribunal_id, count=len(results))
        return results

    # ---- HTML scraping (TJRS, TJSC, TJTO) ----

    async def _search_html(
        self,
        config: dict[str, str],
        tribunal_id: str,
        form_data: dict[str, str],
        max_results: int,
    ) -> list[ResultadoBusca]:
        """POST to eProc HTML endpoint and parse results."""
        url = config["base"] + config["search_path"]
        try:
            busca_circuit_breaker.check(tribunal_id)
        except RuntimeError:
            logger.warning("circuit_open", tribunal_id=tribunal_id)
            return []

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    data=form_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()

            busca_circuit_breaker.record_success(tribunal_id)
            return self._parse_html_results(resp.text, tribunal_id, max_results)

        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError) as exc:
            busca_circuit_breaker.record_failure(tribunal_id)
            logger.warning("eproc_request_failed", tribunal_id=tribunal_id, error=safe_error_text(exc))
            return []

    def _parse_html_results(
        self, html: str, tribunal_id: str, max_results: int
    ) -> list[ResultadoBusca]:
        """Extract case data from eProc HTML response."""
        results: list[ResultadoBusca] = []
        cnj_matches = _CNJ_RE.findall(html)

        # Extract table rows: look for patterns near CNJ numbers
        classe_re = re.compile(
            r"(?:classe|tipo)[:\s]*</?\w*>?\s*([^<\n]{2,80})", re.IGNORECASE
        )
        orgao_re = re.compile(
            r"(?:vara|orgao|[oó]rg[aã]o\s*julgador)[:\s]*</?\w*>?\s*([^<\n]{2,80})",
            re.IGNORECASE,
        )
        data_re = re.compile(
            r"(?:data\s*(?:de\s*)?ajuizamento|distribui[cç][aã]o)[:\s]*</?\w*>?\s*"
            r"(\d{2}/\d{2}/\d{4})",
            re.IGNORECASE,
        )

        classes = classe_re.findall(html)
        orgaos = orgao_re.findall(html)
        datas = data_re.findall(html)

        seen: set[str] = set()
        for i, cnj in enumerate(cnj_matches):
            if cnj in seen:
                continue
            seen.add(cnj)
            if len(results) >= max_results:
                break

            results.append(
                ResultadoBusca(
                    numero_cnj=cnj,
                    tribunal=tribunal_id.upper(),
                    fonte=FonteOrigem.EPROC,
                    classe=classes[i].strip() if i < len(classes) else "",
                    assunto="",
                    orgao_julgador=orgaos[i].strip() if i < len(orgaos) else "",
                    data_ajuizamento=datas[i].strip() if i < len(datas) else "",
                    grau="1",
                    ultima_atualizacao="",
                )
            )

        logger.info("eproc_html_results", tribunal_id=tribunal_id, count=len(results))
        return results


def _extract_polo(item: dict[str, Any], key: str) -> list[str]:
    """Extract party names from a JSON polo field."""
    polo = item.get(key, [])
    if isinstance(polo, list):
        return [
            str(p.get("nome") or p.get("name") or p) if isinstance(p, dict) else str(p)
            for p in polo
        ]
    if isinstance(polo, str):
        return [polo]
    return []
