"""DataJud API client — CNJ's public tribunal data aggregator.

DataJud provides Elasticsearch-backed access to processo data from all
Brazilian tribunals. Used as a fallback when MNI direct access is unavailable
(e.g., TJMG where the MNI login mechanism is broken).

Docs: https://datajud-wiki.cnj.jus.br/
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from juris.core.observability import get_logger
from juris.datajud.safety import (
    DEFAULT_MOVEMENT_TTL,
    DataJudCache,
    DataJudRequestMeta,
    RateLimiter,
    audit_datajud_call,
    default_audit_path,
    query_hash,
)
from juris.persistence.audit import AuditLog

logger = get_logger(__name__)

_BASE_URL = "https://api-publica.datajud.cnj.jus.br"
_API_KEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
_TIMEOUT = 30

# Mapping tribunal_id → DataJud index name
_TRIBUNAL_INDEX: dict[str, str] = {
    # Justiça Estadual
    "tjac": "api_publica_tjac",
    "tjal": "api_publica_tjal",
    "tjam": "api_publica_tjam",
    "tjap": "api_publica_tjap",
    "tjba": "api_publica_tjba",
    "tjce": "api_publica_tjce",
    "tjdf": "api_publica_tjdft",
    "tjes": "api_publica_tjes",
    "tjgo": "api_publica_tjgo",
    "tjma": "api_publica_tjma",
    "tjmg": "api_publica_tjmg",
    "tjms": "api_publica_tjms",
    "tjmt": "api_publica_tjmt",
    "tjpa": "api_publica_tjpa",
    "tjpb": "api_publica_tjpb",
    "tjpe": "api_publica_tjpe",
    "tjpi": "api_publica_tjpi",
    "tjpr": "api_publica_tjpr",
    "tjrj": "api_publica_tjrj",
    "tjrn": "api_publica_tjrn",
    "tjro": "api_publica_tjro",
    "tjrr": "api_publica_tjrr",
    "tjrs": "api_publica_tjrs",
    "tjsc": "api_publica_tjsc",
    "tjse": "api_publica_tjse",
    "tjsp": "api_publica_tjsp",
    "tjto": "api_publica_tjto",
    # Justiça do Trabalho
    "trt1": "api_publica_trt1",
    "trt2": "api_publica_trt2",
    "trt3": "api_publica_trt3",
    "trt4": "api_publica_trt4",
    "trt5": "api_publica_trt5",
    "trt6": "api_publica_trt6",
    "trt7": "api_publica_trt7",
    "trt8": "api_publica_trt8",
    "trt9": "api_publica_trt9",
    "trt10": "api_publica_trt10",
    "trt11": "api_publica_trt11",
    "trt12": "api_publica_trt12",
    "trt13": "api_publica_trt13",
    "trt14": "api_publica_trt14",
    "trt15": "api_publica_trt15",
    "trt16": "api_publica_trt16",
    "trt17": "api_publica_trt17",
    "trt18": "api_publica_trt18",
    "trt19": "api_publica_trt19",
    "trt20": "api_publica_trt20",
    "trt21": "api_publica_trt21",
    "trt22": "api_publica_trt22",
    "trt23": "api_publica_trt23",
    "trt24": "api_publica_trt24",
    "tst": "api_publica_tst",
    # Justiça Federal
    "trf1": "api_publica_trf1",
    "trf2": "api_publica_trf2",
    "trf3": "api_publica_trf3",
    "trf4": "api_publica_trf4",
    "trf5": "api_publica_trf5",
    "trf6": "api_publica_trf6",
    # Superiores
    "stj": "api_publica_stj",
    "stf": "api_publica_stf",
}


def _get_index(tribunal_id: str) -> str:
    """Get the DataJud index name for a tribunal."""
    tribunal_id = tribunal_id.lower().strip()
    if tribunal_id not in _TRIBUNAL_INDEX:
        available = ", ".join(sorted(_TRIBUNAL_INDEX.keys()))
        msg = f"No DataJud index for tribunal '{tribunal_id}'. Available: {available}"
        raise KeyError(msg)
    return _TRIBUNAL_INDEX[tribunal_id]


def _strip_cnj(numero_cnj: str) -> str:
    """Strip formatting from CNJ number: '5082351-40.2017.8.13.0024' → '50823514020178130024'."""
    return numero_cnj.replace("-", "").replace(".", "")


def _hit_count(data: dict[str, Any]) -> int:
    """Extract Elasticsearch hit count from a DataJud response."""
    hits = data.get("hits", {}).get("hits", [])
    return len(hits) if isinstance(hits, list) else 0


def _post_datajud(
    *,
    url: str,
    endpoint: str,
    tribunal_id: str,
    body: dict[str, Any],
    api_key: str,
    numero_cnj: str | None = None,
    cache_dir: Path | None = None,
    audit_path: Path | None = None,
    use_cache: bool = True,
    rate_limiter: RateLimiter | None = None,
    post: Callable[..., httpx.Response] | None = None,
) -> dict[str, Any]:
    """POST to DataJud with cache, rate limit, and audit logging."""
    meta = DataJudRequestMeta(
        cnj=numero_cnj,
        tribunal=tribunal_id.lower().strip(),
        endpoint=endpoint,
        query_hash=query_hash(body),
    )
    cache = DataJudCache(cache_dir)
    audit = AuditLog(audit_path or default_audit_path())

    start = time.monotonic()
    if use_cache:
        cached = cache.get(meta, ttl=DEFAULT_MOVEMENT_TTL)
        if cached is not None:
            audit_datajud_call(
                audit,
                meta,
                cache_hit=True,
                status_code=200,
                duration_ms=(time.monotonic() - start) * 1000,
                result_count=_hit_count(cached),
            )
            logger.info("datajud_cache_hit", tribunal=tribunal_id, endpoint=endpoint)
            return cached

    (rate_limiter or RateLimiter()).wait()
    status_code: int | None = None
    try:
        post_fn = post or httpx.post
        response = post_fn(
            url,
            headers={
                "Authorization": f"APIKey {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=_TIMEOUT,
        )
        status_code = response.status_code
        response.raise_for_status()
        data = response.json()
    except Exception:
        audit_datajud_call(
            audit,
            meta,
            cache_hit=False,
            status_code=status_code,
            duration_ms=(time.monotonic() - start) * 1000,
            result_count=None,
        )
        raise

    if use_cache:
        cache.set(meta, data)
    audit_datajud_call(
        audit,
        meta,
        cache_hit=False,
        status_code=status_code,
        duration_ms=(time.monotonic() - start) * 1000,
        result_count=_hit_count(data),
    )
    return data


def consultar_processo(
    numero_cnj: str,
    tribunal_id: str,
    api_key: str = _API_KEY,
    *,
    cache_dir: Path | None = None,
    audit_path: Path | None = None,
    use_cache: bool = True,
    rate_limiter: RateLimiter | None = None,
) -> dict[str, Any] | None:
    """Fetch a processo from DataJud by CNJ number.

    Args:
        numero_cnj: Case number (with or without formatting).
        tribunal_id: Tribunal identifier (e.g., 'tjmg').
        api_key: DataJud API key (uses default public key).

    Returns:
        The _source dict from DataJud, or None if not found.
    """
    index = _get_index(tribunal_id)
    numero_limpo = _strip_cnj(numero_cnj)

    logger.info("datajud_consulta", numero_cnj=numero_cnj, tribunal=tribunal_id)

    body = {
        "query": {"match": {"numeroProcesso": numero_limpo}},
        "size": 1,
    }
    endpoint = f"/{index}/_search"
    data = _post_datajud(
        url=f"{_BASE_URL}{endpoint}",
        endpoint=endpoint,
        tribunal_id=tribunal_id,
        numero_cnj=numero_cnj,
        api_key=api_key,
        body=body,
        cache_dir=cache_dir,
        audit_path=audit_path,
        use_cache=use_cache,
        rate_limiter=rate_limiter,
    )

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        logger.info("datajud_not_found", numero_cnj=numero_cnj)
        return None

    source = hits[0]["_source"]
    logger.info(
        "datajud_found",
        numero_cnj=numero_cnj,
        movimentos=len(source.get("movimentos", [])),
    )
    return source


def _build_party_query(
    nome: str | None = None,
    cpf: str | None = None,
) -> dict[str, Any]:
    """Build an Elasticsearch query to find processos by party name and/or CPF.

    Note: DataJud's public API does NOT index party data. This function uses
    query_string to search across all indexed fields as a best-effort approach.

    Args:
        nome: Party name (full or partial).
        cpf: CPF number (any format).

    Returns:
        Elasticsearch query dict.
    """
    if not nome and not cpf:
        msg = "At least one of nome or cpf must be provided"
        raise ValueError(msg)

    # DataJud public API doesn't index party data at all.
    # We use query_string as a best-effort search across all fields.
    terms: list[str] = []
    if cpf:
        cpf_limpo = cpf.replace(".", "").replace("-", "").replace(" ", "")
        terms.append(cpf_limpo)
    if nome:
        # Quote the name for exact phrase matching
        terms.append(f'"{nome}"')

    return {"query_string": {"query": " AND ".join(terms)}}


def buscar_processos_por_cpf(
    cpf: str,
    tribunal_id: str,
    max_results: int = 20,
    api_key: str = _API_KEY,
    *,
    cache_dir: Path | None = None,
    audit_path: Path | None = None,
    use_cache: bool = True,
    rate_limiter: RateLimiter | None = None,
) -> list[dict[str, Any]]:
    """Search DataJud for processos involving a CPF (as party document).

    Args:
        cpf: CPF number (any format).
        tribunal_id: Tribunal identifier.
        max_results: Maximum number of results.
        api_key: DataJud API key.

    Returns:
        List of _source dicts from matching processos.
    """
    index = _get_index(tribunal_id)
    query = _build_party_query(cpf=cpf)

    body = {
        "query": query,
        "size": max_results,
        "sort": [{"dataHoraUltimaAtualizacao": {"order": "desc"}}],
    }
    endpoint = f"/{index}/_search"
    data = _post_datajud(
        url=f"{_BASE_URL}{endpoint}",
        endpoint=endpoint,
        tribunal_id=tribunal_id,
        api_key=api_key,
        body=body,
        cache_dir=cache_dir,
        audit_path=audit_path,
        use_cache=use_cache,
        rate_limiter=rate_limiter,
    )

    hits = data.get("hits", {}).get("hits", [])
    return [h["_source"] for h in hits]


def buscar_parte_tribunal(
    tribunal_id: str,
    nome: str | None = None,
    cpf: str | None = None,
    max_results: int = 20,
    api_key: str = _API_KEY,
    *,
    cache_dir: Path | None = None,
    audit_path: Path | None = None,
    use_cache: bool = True,
    rate_limiter: RateLimiter | None = None,
) -> list[dict[str, Any]]:
    """Search a single tribunal for processos by party name and/or CPF.

    Args:
        tribunal_id: Tribunal identifier.
        nome: Party name.
        cpf: CPF number.
        max_results: Maximum results per tribunal.
        api_key: DataJud API key.

    Returns:
        List of _source dicts with tribunal_id injected.
    """
    index = _get_index(tribunal_id)
    query = _build_party_query(nome=nome, cpf=cpf)

    logger.info("datajud_busca_parte", tribunal=tribunal_id, nome=nome, cpf=cpf)

    try:
        body = {
            "query": query,
            "size": max_results,
            "_source": {
                "excludes": ["movimentos"],
            },
        }
        endpoint = f"/{index}/_search"
        data = _post_datajud(
            url=f"{_BASE_URL}{endpoint}",
            endpoint=endpoint,
            tribunal_id=tribunal_id,
            api_key=api_key,
            body=body,
            cache_dir=cache_dir,
            audit_path=audit_path,
            use_cache=use_cache,
            rate_limiter=rate_limiter,
        )
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning("datajud_busca_parte_error", tribunal=tribunal_id, error=str(e))
        return []

    hits = data.get("hits", {}).get("hits", [])

    results = []
    for h in hits:
        source = h["_source"]
        source["_tribunal_id"] = tribunal_id
        source["_score"] = h.get("_score", 0)
        results.append(source)

    logger.info("datajud_busca_parte_found", tribunal=tribunal_id, count=len(results))
    return results


def buscar_parte_todos_tribunais(
    nome: str | None = None,
    cpf: str | None = None,
    tribunais: list[str] | None = None,
    max_per_tribunal: int = 10,
    api_key: str = _API_KEY,
    *,
    cache_dir: Path | None = None,
    audit_path: Path | None = None,
    use_cache: bool = True,
    rate_limiter: RateLimiter | None = None,
) -> list[dict[str, Any]]:
    """Search multiple tribunals for processos by party name and/or CPF.

    Queries tribunals concurrently for speed.

    Args:
        nome: Party name.
        cpf: CPF number.
        tribunais: List of tribunal IDs to search. Defaults to all.
        max_per_tribunal: Max results per tribunal.
        api_key: DataJud API key.

    Returns:
        Combined list of _source dicts from all tribunals, sorted by score.
    """
    if tribunais is None:
        tribunais = list(_TRIBUNAL_INDEX.keys())

    all_results: list[dict[str, Any]] = []

    with httpx.Client(timeout=_TIMEOUT) as client:
        query = _build_party_query(nome=nome, cpf=cpf)
        resolved_limiter = rate_limiter or RateLimiter()
        body = {
            "query": query,
            "size": max_per_tribunal,
            "_source": {
                "excludes": ["movimentos"],
            },
        }

        for tribunal_id in tribunais:
            index = _TRIBUNAL_INDEX[tribunal_id]
            logger.debug("datajud_busca_parte_tribunal", tribunal=tribunal_id)

            try:
                endpoint = f"/{index}/_search"
                data = _post_datajud(
                    url=f"{_BASE_URL}{endpoint}",
                    endpoint=endpoint,
                    tribunal_id=tribunal_id,
                    api_key=api_key,
                    body=body,
                    cache_dir=cache_dir,
                    audit_path=audit_path,
                    use_cache=use_cache,
                    rate_limiter=resolved_limiter,
                    post=client.post,
                )
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("datajud_busca_parte_skip", tribunal=tribunal_id, error=str(e))
                continue

            hits = data.get("hits", {}).get("hits", [])
            for h in hits:
                source = h["_source"]
                source["_tribunal_id"] = tribunal_id
                source["_score"] = h.get("_score", 0)
                all_results.append(source)

    # Sort by score descending
    all_results.sort(key=lambda r: r.get("_score", 0), reverse=True)

    logger.info(
        "datajud_busca_parte_total",
        tribunais_searched=len(tribunais),
        total_found=len(all_results),
    )
    return all_results


def list_available_tribunais() -> list[str]:
    """Return all tribunal IDs available in the DataJud index."""
    return sorted(_TRIBUNAL_INDEX.keys())
