"""ESAJ search channel — async scraping across 12 state tribunals."""

from __future__ import annotations

import re

import httpx

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem, ResultadoBusca
from juris.busca.retry import busca_circuit_breaker
from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text

logger = get_logger(__name__)

_TIMEOUT = 20

_ESAJ_URLS: dict[str, dict[str, str]] = {
    "tjsp": {"base": "https://esaj.tjsp.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjms": {"base": "https://esaj.tjms.jus.br", "1g": "/cpopg5", "2g": "/cposg5"},
    "tjal": {"base": "https://www2.tjal.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjce": {"base": "https://esaj.tjce.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjam": {
        "base": "https://consultasaj.tjam.jus.br",
        "1g": "/cpopg",
        "2g": "/cposg",
    },
    "tjac": {"base": "https://esaj.tjac.jus.br", "1g": "/cpopg"},
    "tjba": {"base": "https://esaj.tjba.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjpi": {"base": "https://esaj.tjpi.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjrn": {"base": "https://esaj.tjrn.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjgo": {"base": "https://esaj.tjgo.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjsc": {"base": "https://esaj.tjsc.jus.br", "1g": "/cpopg", "2g": "/cposg"},
    "tjrr": {"base": "https://esaj.tjrr.jus.br", "1g": "/cpopg", "2g": "/cposg"},
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# Regex patterns for parsing ESAJ HTML results.
_ENTRY_RE = re.compile(
    r"processo\.codigo=([^&\"]+).*?"
    r"([0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4})",
    re.DOTALL,
)
_CLASSE_RE = re.compile(r'classeProcesso["\s>]+([^<]+)')
_ASSUNTO_RE = re.compile(r'assuntoPrincipalProcesso["\s>]+([^<]+)')
_DATA_VARA_RE = re.compile(r'dataLocalDistribuicaoProcesso["\s>]+([^<]+)')
_POLO_RE = re.compile(r'tipoDeParticipacao["\s>]+([^<:]+)')
_NOME_RE = re.compile(r'nomeParte["\s>]+\s*([^<]+)')


def _parse_esaj_results(
    html: str, tribunal_id: str, grau: str,
) -> list[ResultadoBusca]:
    """Parse ESAJ search result HTML into ResultadoBusca list."""
    results: list[ResultadoBusca] = []

    entries = _ENTRY_RE.findall(html)
    if not entries:
        return results

    grau_label = "1" if grau == "1g" else "2"

    for _, numero_cnj in entries:
        idx = html.index(numero_cnj)
        start = max(0, idx - 200)
        end = min(len(html), idx + 2000)
        block = html[start:end]

        classe_match = _CLASSE_RE.search(block)
        classe = classe_match.group(1).strip() if classe_match else ""

        assunto_match = _ASSUNTO_RE.search(block)
        assunto = assunto_match.group(1).strip() if assunto_match else ""

        data_vara_match = _DATA_VARA_RE.search(block)
        data_vara = data_vara_match.group(1).strip() if data_vara_match else ""
        data_aj = ""
        orgao = ""
        if " - " in data_vara:
            parts = data_vara.split(" - ", 1)
            data_aj = parts[0].strip()
            orgao = parts[1].strip()
        elif data_vara:
            data_aj = data_vara

        polo_match = _POLO_RE.search(block)
        polo_tipo = polo_match.group(1).strip().lower() if polo_match else ""

        nome_match = _NOME_RE.search(block)
        nome_parte = nome_match.group(1).strip() if nome_match else ""

        polo_ativo: list[str] = []
        polo_passivo: list[str] = []
        if nome_parte:
            if any(
                k in polo_tipo
                for k in ("autor", "requerent", "exequent", "reconvind")
            ):
                polo_ativo.append(nome_parte)
            elif any(
                k in polo_tipo
                for k in ("réu", "reu", "requerid", "executad", "reconvint")
            ):
                polo_passivo.append(nome_parte)
            else:
                polo_ativo.append(
                    f"{nome_parte} ({polo_tipo})" if polo_tipo else nome_parte,
                )

        results.append(
            ResultadoBusca(
                numero_cnj=numero_cnj,
                tribunal=tribunal_id.upper(),
                fonte=FonteOrigem.ESAJ,
                classe=classe,
                assunto=assunto,
                orgao_julgador=orgao,
                data_ajuizamento=data_aj,
                grau=grau_label,
                ultima_atualizacao="",
                polo_ativo=polo_ativo,
                polo_passivo=polo_passivo,
            ),
        )

    return results


class EsajChannel(SearchChannel):
    """Async ESAJ scraping channel covering 12 state tribunals."""

    @property
    def channel_name(self) -> FonteOrigem:
        """Return the channel's FonteOrigem identifier."""
        return FonteOrigem.ESAJ

    def supported_tribunais(self) -> list[str]:
        """Return sorted list of tribunal IDs this channel can query."""
        return sorted(_ESAJ_URLS.keys())

    async def search_by_name(
        self, tribunal_id: str, nome: str, max_results: int = 20,
    ) -> list[ResultadoBusca]:
        """Search by party name."""
        return await self._search(
            tribunal_id, cb_pesquisa="NMPARTE", valor=nome,
            max_results=max_results,
        )

    async def search_by_cpf(
        self, tribunal_id: str, cpf: str, max_results: int = 20,
    ) -> list[ResultadoBusca]:
        """Search by CPF/CNPJ document number."""
        valor = re.sub(r"[.\-/ ]", "", cpf)
        return await self._search(
            tribunal_id, cb_pesquisa="DOCPARTE", valor=valor,
            max_results=max_results,
        )

    async def search_by_oab(
        self, tribunal_id: str, oab: str, max_results: int = 20,
    ) -> list[ResultadoBusca]:
        """Search by OAB registration number."""
        return await self._search(
            tribunal_id, cb_pesquisa="NUMOAB", valor=oab,
            max_results=max_results,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search(
        self,
        tribunal_id: str,
        cb_pesquisa: str,
        valor: str,
        max_results: int,
    ) -> list[ResultadoBusca]:
        """Execute search across both degrees for a single tribunal."""
        tid = tribunal_id.lower()
        config = _ESAJ_URLS.get(tid)
        if not config:
            logger.debug("esaj_tribunal_not_supported", tribunal=tribunal_id)
            return []

        try:
            busca_circuit_breaker.check(tid)
        except RuntimeError:
            logger.debug("esaj_circuit_open", tribunal=tid)
            return []

        base_url = config["base"]
        graus = [g for g in ("1g", "2g") if g in config]
        all_results: list[ResultadoBusca] = []

        for grau in graus:
            path = config[grau]
            results = await self._fetch_grau(
                base_url, path, tid, grau, cb_pesquisa, valor,
            )
            all_results.extend(results)
            if len(all_results) >= max_results:
                break

        if all_results:
            busca_circuit_breaker.record_success(tid)
        return all_results[:max_results]

    async def _fetch_grau(
        self,
        base_url: str,
        path: str,
        tribunal_id: str,
        grau: str,
        cb_pesquisa: str,
        valor: str,
    ) -> list[ResultadoBusca]:
        """Fetch and parse results for a single degree of a tribunal."""
        session_url = f"{base_url}{path}/open.do"
        search_url = f"{base_url}{path}/search.do"
        params = {
            "conversationId": "",
            "dadosConsulta.localPesquisa.cdLocal": "-1",
            "cbPesquisa": cb_pesquisa,
            "dadosConsulta.valorConsulta": valor,
            "dadosConsulta.tipoNuProcesso": "UNIFICADO",
        }

        logger.debug(
            "esaj_fetch_grau",
            tribunal=tribunal_id,
            grau=grau,
            tipo=cb_pesquisa,
        )

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, follow_redirects=True,
            ) as client:
                # Establish session (cookies)
                await client.get(session_url, headers=_HEADERS)

                # Execute search
                response = await client.get(
                    search_url, params=params, headers=_HEADERS,
                )
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ConnectTimeout,
        ) as exc:
            logger.debug(
                "esaj_fetch_error",
                tribunal=tribunal_id,
                grau=grau,
                error=safe_error_text(exc),
            )
            busca_circuit_breaker.record_failure(tribunal_id)
            return []

        if response.status_code != 200:
            logger.debug(
                "esaj_fetch_failed",
                tribunal=tribunal_id,
                grau=grau,
                status=response.status_code,
            )
            busca_circuit_breaker.record_failure(tribunal_id)
            return []

        html = response.text

        if "Não existem informações disponíveis" in html:
            logger.debug("esaj_no_results", tribunal=tribunal_id, grau=grau)
            return []

        if "Foram encontrados muitos processos" in html:
            logger.warning(
                "esaj_too_many_results", tribunal=tribunal_id, grau=grau,
            )
            return []

        results = _parse_esaj_results(html, tribunal_id, grau)
        logger.info(
            "esaj_fetch_found",
            tribunal=tribunal_id,
            grau=grau,
            count=len(results),
        )
        return results
