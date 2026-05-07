"""DataJud search channel — wraps the sync DataJud client as an async SearchChannel.

DataJud is the CNJ's public Elasticsearch-backed API that aggregates processo data
from all Brazilian tribunals. Party search is best-effort since DataJud does NOT
reliably index party data (names, CPFs). OAB search is not supported at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem, ResultadoBusca
from juris.busca.retry import busca_circuit_breaker
from juris.core.observability import get_logger
from juris.datajud.client import _TRIBUNAL_INDEX, buscar_parte_tribunal

logger = get_logger(__name__)


def _format_cnj(numero_raw: str) -> str:
    """Format a raw 20-digit CNJ number into NNNNNNN-DD.AAAA.J.TR.OOOO.

    Args:
        numero_raw: Raw digits, e.g. '50823514020178130024'.

    Returns:
        Formatted string, e.g. '5082351-40.2017.8.13.0024'.
    """
    n = numero_raw.strip().replace("-", "").replace(".", "")
    if len(n) != 20:
        return numero_raw  # Return as-is if unexpected length
    return f"{n[:7]}-{n[7:9]}.{n[9:13]}.{n[13]}.{n[14:16]}.{n[16:20]}"


def _extract_assuntos(assuntos: list[dict[str, Any]]) -> str:
    """Join assunto names from the DataJud assuntos list."""
    nomes = [a.get("nome", "") for a in assuntos if a.get("nome")]
    return "; ".join(nomes) if nomes else ""


def _to_resultado(hit: dict[str, Any]) -> ResultadoBusca:
    """Convert a DataJud _source dict into a ResultadoBusca."""
    numero_raw = hit.get("numeroProcesso", "")
    tribunal_id = hit.get("_tribunal_id", "")

    classe_obj = hit.get("classe") or {}
    assuntos_list = hit.get("assuntos") or []
    orgao_obj = hit.get("orgaoJulgador") or {}

    return ResultadoBusca(
        numero_cnj=_format_cnj(numero_raw),
        tribunal=tribunal_id.upper(),
        fonte=FonteOrigem.DATAJUD,
        classe=classe_obj.get("nome", ""),
        assunto=_extract_assuntos(assuntos_list),
        orgao_julgador=orgao_obj.get("nome", ""),
        data_ajuizamento=hit.get("dataAjuizamento", ""),
        grau=hit.get("grau", ""),
        ultima_atualizacao=hit.get("dataHoraUltimaAtualizacao", ""),
        raw=hit,
    )


class DataJudChannel(SearchChannel):
    """Async search channel backed by the DataJud public API.

    All calls delegate to the sync ``buscar_parte_tribunal`` via
    ``asyncio.to_thread`` so the event loop stays unblocked.

    DataJud does NOT reliably index party data (names, CPFs), so results
    from this channel are best-effort and should be corroborated with
    primary sources (e.g., eSAJ, eProc).
    """

    @property
    def channel_name(self) -> FonteOrigem:
        """Return the channel identifier."""
        return FonteOrigem.DATAJUD

    def supported_tribunais(self) -> list[str]:
        """Return all 62+ tribunal IDs available in DataJud."""
        return sorted(_TRIBUNAL_INDEX.keys())

    async def _search(
        self,
        tribunal_id: str,
        *,
        nome: str | None = None,
        cpf: str | None = None,
        max_results: int = 20,
    ) -> list[ResultadoBusca]:
        """Internal search dispatching to the sync client via asyncio.to_thread.

        Args:
            tribunal_id: Tribunal identifier (e.g. 'tjmg').
            nome: Party name for search.
            cpf: CPF/CNPJ document number.
            max_results: Maximum number of results.

        Returns:
            List of converted ResultadoBusca objects.
        """
        tid = tribunal_id.lower().strip()

        try:
            busca_circuit_breaker.check(tid)
        except RuntimeError:
            logger.warning("datajud_circuit_open", tribunal=tid)
            return []

        try:
            hits: list[dict[str, Any]] = await asyncio.to_thread(
                buscar_parte_tribunal,
                tribunal_id=tid,
                nome=nome,
                cpf=cpf,
                max_results=max_results,
            )
        except Exception:
            busca_circuit_breaker.record_failure(tid)
            logger.exception("datajud_search_error", tribunal=tid)
            return []

        busca_circuit_breaker.record_success(tid)

        results = [_to_resultado(h) for h in hits]
        logger.info(
            "datajud_channel_results",
            tribunal=tid,
            count=len(results),
        )
        return results

    async def search_by_name(
        self, tribunal_id: str, nome: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search DataJud by party name (best-effort)."""
        return await self._search(
            tribunal_id, nome=nome, max_results=max_results
        )

    async def search_by_cpf(
        self, tribunal_id: str, cpf: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search DataJud by CPF/CNPJ (best-effort)."""
        return await self._search(
            tribunal_id, cpf=cpf, max_results=max_results
        )

    async def search_by_oab(
        self, tribunal_id: str, oab: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """DataJud does not support OAB search. Always returns empty list."""
        logger.debug("datajud_oab_not_supported", tribunal=tribunal_id)
        return []
