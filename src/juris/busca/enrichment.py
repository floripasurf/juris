"""DataJud enrichment — adds movimentos count and valor_causa to consolidated results."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from juris.busca.models import ResultadoConsolidado
from juris.core.observability import get_logger
from juris.datajud.client import consultar_processo
from juris.datajud.parser import parse_datajud_processo

logger = get_logger(__name__)


async def enrich_resultado(
    resultado: ResultadoConsolidado,
) -> ResultadoConsolidado:
    """Enrich a single consolidated result with DataJud data.

    Calls ``consultar_processo`` in a thread to avoid blocking the event loop,
    then extracts movimentos count and valor_causa from the response.

    Args:
        resultado: The consolidated result to enrich.

    Returns:
        A new ``ResultadoConsolidado`` with enrichment fields populated,
        or the original if the lookup fails.
    """
    try:
        source = await asyncio.to_thread(
            consultar_processo,
            resultado.numero_cnj,
            resultado.tribunal,
        )
    except Exception:
        logger.exception(
            "enrich_error",
            numero_cnj=resultado.numero_cnj,
            tribunal=resultado.tribunal,
        )
        return replace(resultado, enriquecido=False)

    if source is None:
        logger.info(
            "enrich_not_found",
            numero_cnj=resultado.numero_cnj,
        )
        return replace(resultado, enriquecido=False)

    processo = parse_datajud_processo(source)
    movimentos_count = len(processo.movimentos)

    valor_causa: float | None = None
    valor_obj = source.get("valorCausa")
    if isinstance(valor_obj, dict):
        valor_causa = valor_obj.get("valor")
    elif isinstance(valor_obj, (int, float)):
        valor_causa = float(valor_obj)

    logger.info(
        "enrich_success",
        numero_cnj=resultado.numero_cnj,
        movimentos=movimentos_count,
        valor_causa=valor_causa,
    )

    return replace(
        resultado,
        enriquecido=True,
        dados_datajud=source,
        movimentos_count=movimentos_count,
        valor_causa=valor_causa,
    )


async def enrich_batch(
    resultados: list[ResultadoConsolidado],
    max_concurrent: int = 10,
) -> list[ResultadoConsolidado]:
    """Enrich a batch of consolidated results concurrently.

    Uses a semaphore to limit the number of concurrent DataJud API calls.

    Args:
        resultados: List of results to enrich.
        max_concurrent: Maximum number of concurrent enrichment calls.

    Returns:
        Enriched list in the same order as the input.
    """
    if not resultados:
        return []

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _limited_enrich(r: ResultadoConsolidado) -> ResultadoConsolidado:
        async with semaphore:
            return await enrich_resultado(r)

    enriched = await asyncio.gather(*[_limited_enrich(r) for r in resultados])

    logger.info(
        "enrich_batch_done",
        total=len(enriched),
        enriched_count=sum(1 for r in enriched if r.enriquecido),
    )

    return list(enriched)
