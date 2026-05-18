"""Search orchestrator — parallel dispatch, dedup, enrichment, scoring."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from juris.busca.abc import SearchChannel
from juris.busca.cache import BuscaCache
from juris.busca.enrichment import enrich_batch
from juris.busca.models import (
    BuscaRequest,
    FonteOrigem,
    RelatoriosBusca,
    ResultadoBusca,
    ResultadoConsolidado,
)
from juris.busca.registry import ChannelRegistry
from juris.core.observability import get_logger
from juris.datajud.safety import ensure_batch_allowed

logger = get_logger(__name__)

# Channels considered reliable for party search (vs DataJud best-effort).
_RELIABLE_SOURCES: frozenset[FonteOrigem] = frozenset({
    FonteOrigem.ESAJ,
    FonteOrigem.EPROC,
    FonteOrigem.EJEF,
    FonteOrigem.PROJUDI,
})

# Priority for field merging when the same CNJ appears in multiple channels.
_SOURCE_PRIORITY: dict[FonteOrigem, int] = {
    FonteOrigem.ESAJ: 5,
    FonteOrigem.EPROC: 4,
    FonteOrigem.EJEF: 3,
    FonteOrigem.PROJUDI: 2,
    FonteOrigem.DATAJUD: 1,
}


class SearchOrchestrator:
    """Core search engine — queries all channels in parallel, deduplicates,
    enriches via DataJud, and scores results by corroboration.

    Args:
        registry: Channel registry. Auto-discovers if ``None``.
        cache: Result cache. Disabled if ``None``.
        enrich: Whether to enrich results via DataJud.
        max_concurrent_channels: Concurrency limit for channel queries.
    """

    def __init__(
        self,
        registry: ChannelRegistry | None = None,
        cache: BuscaCache | None = None,
        enrich: bool = True,
        max_concurrent_channels: int = 20,
        confirm_datajud_batch: bool = False,
    ) -> None:
        self._registry = registry or ChannelRegistry()
        self._cache = cache
        self._enrich = enrich
        self._confirm_datajud_batch = confirm_datajud_batch
        self._semaphore = asyncio.Semaphore(max_concurrent_channels)

    async def search(self, request: BuscaRequest) -> RelatoriosBusca:
        """Execute a full multi-channel search.

        1. Check cache
        2. Build (tribunal, channel) pairs
        3. asyncio.gather all searches with Semaphore
        4. Collect results, log errors per tribunal
        5. Deduplicate by CNJ number
        6. Enrich via DataJud (batch)
        7. Compute corroboration scores
        8. Sort by confidence descending
        9. Cache results
        10. Return RelatoriosBusca
        """
        t0 = time.monotonic()

        # 1. Cache check
        if self._cache:
            cached = self._cache.get(request)
            if cached is not None:
                logger.info("search_cache_hit")
                return cached

        # 2. Build (tribunal, channel) pairs
        tribunais = request.tribunais or self._registry.all_tribunais()
        pairs: list[tuple[str, SearchChannel]] = []
        for tid in tribunais:
            for ch in self._registry.get_channels(tid):
                pairs.append((tid, ch))

        datajud_pairs = sum(1 for _, ch in pairs if ch.channel_name == FonteOrigem.DATAJUD)
        if datajud_pairs:
            ensure_batch_allowed(
                cnj_count=datajud_pairs,
                confirm_batch=self._confirm_datajud_batch,
                calls_per_cnj=1,
                item_label="consultas por tribunal",
            )

        logger.info(
            "search_dispatching",
            tribunais=len(tribunais),
            pairs=len(pairs),
        )

        # 3. Parallel dispatch
        tribunais_com_erro: list[str] = []
        all_results: list[ResultadoBusca] = []
        canais_set: set[FonteOrigem] = set()

        async def _query(tid: str, ch: SearchChannel) -> list[ResultadoBusca]:
            async with self._semaphore:
                try:
                    results = await self._dispatch_search(ch, tid, request)
                    canais_set.add(ch.channel_name)
                    return results
                except Exception:
                    logger.exception("channel_error", tribunal=tid, channel=ch.channel_name.value)
                    if tid not in tribunais_com_erro:
                        tribunais_com_erro.append(tid)
                    return []

        tasks = [_query(tid, ch) for tid, ch in pairs]
        results_lists = await asyncio.gather(*tasks)

        for results in results_lists:
            all_results.extend(results)

        # 5. Dedup by CNJ number
        consolidated = self._deduplicate(all_results)

        # 6. Enrich
        if self._enrich and consolidated:
            consolidated = await enrich_batch(
                consolidated,
                confirm_batch=self._confirm_datajud_batch,
            )

        # 7. Score
        has_cpf = bool(request.cpf)
        consolidated = [self._score(r, has_cpf) for r in consolidated]

        # 8. Sort
        consolidated.sort(key=lambda r: r.confianca, reverse=True)

        elapsed = time.monotonic() - t0

        relatorio = RelatoriosBusca(
            request=request,
            resultados=consolidated,
            total_encontrado=len(consolidated),
            tribunais_consultados=len(tribunais),
            tribunais_com_erro=tribunais_com_erro,
            canais_usados=sorted(canais_set, key=lambda f: f.value),
            duracao_segundos=round(elapsed, 2),
        )

        # 9. Cache
        if self._cache:
            self._cache.put(request, relatorio)

        logger.info(
            "search_complete",
            total=len(consolidated),
            tribunais=len(tribunais),
            errors=len(tribunais_com_erro),
            duration=round(elapsed, 2),
        )

        return relatorio

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch_search(
        self,
        channel: SearchChannel,
        tribunal_id: str,
        request: BuscaRequest,
    ) -> list[ResultadoBusca]:
        """Dispatch the appropriate search method based on request fields."""
        results: list[ResultadoBusca] = []

        if request.cpf:
            results = await channel.search_by_cpf(
                tribunal_id, request.cpf, request.max_per_tribunal,
            )
        if request.oab and not results:
            results = await channel.search_by_oab(
                tribunal_id, request.oab, request.max_per_tribunal,
            )
        if request.nome and not results:
            results = await channel.search_by_name(
                tribunal_id, request.nome, request.max_per_tribunal,
            )

        return results

    def _deduplicate(
        self, results: list[ResultadoBusca],
    ) -> list[ResultadoConsolidado]:
        """Merge results by CNJ number.

        When the same CNJ is found in multiple channels, fields are taken
        from the highest-priority source. Party lists are unioned.
        """
        groups: dict[str, list[ResultadoBusca]] = {}
        for r in results:
            groups.setdefault(r.numero_cnj, []).append(r)

        consolidated: list[ResultadoConsolidado] = []
        for cnj, group in groups.items():
            # Sort by priority (highest first)
            group.sort(
                key=lambda r: _SOURCE_PRIORITY.get(r.fonte, 0),
                reverse=True,
            )
            best = group[0]

            # Union polo lists
            polo_ativo: list[str] = []
            polo_passivo: list[str] = []
            seen_at: set[str] = set()
            seen_pa: set[str] = set()
            for r in group:
                for p in r.polo_ativo:
                    if p not in seen_at:
                        seen_at.add(p)
                        polo_ativo.append(p)
                for p in r.polo_passivo:
                    if p not in seen_pa:
                        seen_pa.add(p)
                        polo_passivo.append(p)

            fontes = list(dict.fromkeys(r.fonte for r in group))

            consolidated.append(
                ResultadoConsolidado(
                    numero_cnj=cnj,
                    tribunal=best.tribunal,
                    classe=best.classe,
                    assunto=best.assunto,
                    orgao_julgador=best.orgao_julgador,
                    data_ajuizamento=best.data_ajuizamento,
                    grau=best.grau,
                    ultima_atualizacao=best.ultima_atualizacao,
                    polo_ativo=polo_ativo,
                    polo_passivo=polo_passivo,
                    fontes=fontes,
                )
            )

        return consolidated

    def _score(
        self, resultado: ResultadoConsolidado, has_cpf: bool,
    ) -> ResultadoConsolidado:
        """Compute corroboration confidence score.

        Scoring:
        - Base 0.5 if found in a reliable channel (ESAJ/eProc/EJEF/PROJUDI)
        - Base 0.3 if found only in DataJud
        - +0.15 per additional corroborating source (capped at 1.0)
        - +0.1 if DataJud enrichment succeeded
        - +0.05 if CPF was used in the search
        """
        fontes = resultado.fontes
        has_reliable = any(f in _RELIABLE_SOURCES for f in fontes)
        base = 0.5 if has_reliable else 0.3

        extra_sources = max(0, len(fontes) - 1)
        score = base + (extra_sources * 0.15)

        if resultado.enriquecido:
            score += 0.1
        if has_cpf:
            score += 0.05

        score = min(score, 1.0)

        return replace(resultado, confianca=round(score, 2))
