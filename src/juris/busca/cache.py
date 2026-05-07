"""SQLite-backed search cache for BuscaRequest → RelatoriosBusca lookups."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from juris.busca.models import (
    BuscaRequest,
    FonteOrigem,
    RelatoriosBusca,
    ResultadoConsolidado,
)
from juris.core.observability import get_logger

logger = get_logger(__name__)


class BuscaCache:
    """Lightweight SQLite cache for search results.

    Args:
        db_path: Path to the SQLite database file. ``None`` uses in-memory DB.
        ttl_seconds: Time-to-live in seconds for cache entries.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        self._ttl = ttl_seconds
        db = str(db_path) if db_path else ":memory:"
        self._conn = sqlite3.connect(db)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS busca_cache "
            "(key TEXT PRIMARY KEY, data TEXT, created_at REAL)"
        )
        self._conn.commit()

    def _cache_key(self, request: BuscaRequest) -> str:
        """Build a deterministic SHA-256 key from a search request.

        Normalizes nome (lowercase), CPF (digits only), and tribunais (sorted)
        before hashing so equivalent requests produce the same key.
        """
        nome = (request.nome or "").lower().strip()
        cpf = (request.cpf or "").replace(".", "").replace("-", "").replace(" ", "")
        oab = (request.oab or "").strip()
        tribunais = sorted(request.tribunais) if request.tribunais else []

        payload = json.dumps(
            {"nome": nome, "cpf": cpf, "oab": oab, "tribunais": tribunais},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, request: BuscaRequest) -> RelatoriosBusca | None:
        """Look up a cached search result.

        Args:
            request: The search request to look up.

        Returns:
            Cached ``RelatoriosBusca`` if found and not expired, else ``None``.
        """
        key = self._cache_key(request)
        row = self._conn.execute(
            "SELECT data, created_at FROM busca_cache WHERE key = ?", (key,)
        ).fetchone()

        if row is None:
            return None

        data_str, created_at = row
        if time.time() - created_at > self._ttl:
            self._conn.execute("DELETE FROM busca_cache WHERE key = ?", (key,))
            self._conn.commit()
            logger.debug("cache_expired", key=key[:12])
            return None

        logger.debug("cache_hit", key=key[:12])
        return _deserialize_relatorio(data_str)

    def put(self, request: BuscaRequest, relatorio: RelatoriosBusca) -> None:
        """Store a search result in the cache.

        Args:
            request: The search request (used as key).
            relatorio: The search report to cache.
        """
        key = self._cache_key(request)
        data_str = _serialize_relatorio(relatorio)
        self._conn.execute(
            "INSERT OR REPLACE INTO busca_cache (key, data, created_at) "
            "VALUES (?, ?, ?)",
            (key, data_str, time.time()),
        )
        self._conn.commit()
        logger.debug("cache_put", key=key[:12])

    def invalidate(self, request: BuscaRequest) -> None:
        """Remove a cached entry.

        Args:
            request: The search request whose cache entry to remove.
        """
        key = self._cache_key(request)
        self._conn.execute("DELETE FROM busca_cache WHERE key = ?", (key,))
        self._conn.commit()
        logger.debug("cache_invalidated", key=key[:12])


def _serialize_relatorio(relatorio: RelatoriosBusca) -> str:
    """Serialize a RelatoriosBusca to JSON string."""
    d = asdict(relatorio)
    # Convert FonteOrigem enums to their string values
    d["canais_usados"] = [f.value if isinstance(f, FonteOrigem) else f for f in relatorio.canais_usados]
    for r in d["resultados"]:
        r["fontes"] = [
            f.value if isinstance(f, FonteOrigem) else f for f in (r.get("fontes") or [])
        ]
    return json.dumps(d, ensure_ascii=False, default=str)


def _deserialize_relatorio(data_str: str) -> RelatoriosBusca:
    """Deserialize a JSON string back into a RelatoriosBusca."""
    d: dict[str, Any] = json.loads(data_str)

    request = BuscaRequest(
        nome=d["request"].get("nome"),
        cpf=d["request"].get("cpf"),
        oab=d["request"].get("oab"),
        tribunais=d["request"].get("tribunais"),
        max_per_tribunal=d["request"].get("max_per_tribunal", 20),
    )

    resultados = [
        ResultadoConsolidado(
            numero_cnj=r["numero_cnj"],
            tribunal=r["tribunal"],
            classe=r["classe"],
            assunto=r["assunto"],
            orgao_julgador=r["orgao_julgador"],
            data_ajuizamento=r["data_ajuizamento"],
            grau=r["grau"],
            ultima_atualizacao=r["ultima_atualizacao"],
            polo_ativo=r.get("polo_ativo", []),
            polo_passivo=r.get("polo_passivo", []),
            fontes=[FonteOrigem(f) for f in r.get("fontes", [])],
            confianca=r.get("confianca", 0.0),
            enriquecido=r.get("enriquecido", False),
            dados_datajud=r.get("dados_datajud"),
            movimentos_count=r.get("movimentos_count", 0),
            valor_causa=r.get("valor_causa"),
        )
        for r in d.get("resultados", [])
    ]

    return RelatoriosBusca(
        request=request,
        resultados=resultados,
        total_encontrado=d["total_encontrado"],
        tribunais_consultados=d["tribunais_consultados"],
        tribunais_com_erro=d.get("tribunais_com_erro", []),
        canais_usados=[FonteOrigem(c) for c in d.get("canais_usados", [])],
        duracao_segundos=d["duracao_segundos"],
        do_cache=True,
    )
