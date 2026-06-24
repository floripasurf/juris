"""Overnight sync job — differential read across all tracked processos.

This is the core "Read" loop. It iterates every processo the firm tracks,
fetches fresh data from MNI (or DataJud as fallback), detects new movements
and documents, persists them, and stores new document PDFs.

Entry points:
- `run_overnight_sync()` — async, for programmatic use
- `main()` — sync wrapper for cron/systemd
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from juris.core.observability import get_logger, new_correlation_id
from juris.mni.operations.differential import DiffResult, diff_processo
from juris.mni.parsers.processo import ProcessoDomain, parse_processo
from juris.mni.retry import circuit_breaker

logger = get_logger(__name__)


@dataclass(slots=True)
class SyncSummary:
    """Summary of an overnight sync run."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    processos_checked: int = 0
    processos_updated: int = 0
    processos_failed: int = 0
    new_movimentos_total: int = 0
    new_documentos_total: int = 0
    errors: list[str] = field(default_factory=list)
    results: list[DiffResult] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at is None:
            return 0
        return (self.finished_at - self.started_at).total_seconds()


async def sync_processo_mni(
    numero_cnj: str,
    tribunal_id: str,
    cpf: str,
    senha: str,
    last_sync_at: datetime | None = None,
    known_movimento_keys: set[tuple] | None = None,
    known_doc_ids: set[str] | None = None,
    token_pin: str | None = None,
) -> DiffResult:
    """Sync a single processo via MNI.

    Args:
        numero_cnj: Case number.
        tribunal_id: Tribunal identifier.
        cpf: Lawyer's CPF.
        senha: Password or CPF for cert auth.
        last_sync_at: Last sync timestamp.
        known_movimento_keys: Existing movement keys.
        known_doc_ids: Existing document IDs.

    Returns:
        DiffResult with detected changes.
    """
    from juris.mni.auth import PasswordAuth
    from juris.mni.client import get_mni_client
    from juris.mni.operations.consulta import consultar_processo
    from juris.mni.tribunais import get_tribunal

    try:
        circuit_breaker.check(tribunal_id)
    except RuntimeError as e:
        return DiffResult(
            numero_cnj=numero_cnj,
            tribunal_id=tribunal_id,
            error=f"Circuit open: {e}",
        )

    try:
        tribunal_cfg = get_tribunal(tribunal_id)
    except KeyError:
        tribunal_cfg = None

    try:
        # mTLS tribunals (e.g. TJMG) authenticate with the A3 hardware token,
        # not zeep+password. Route them through the PKCS#11 path.
        if tribunal_cfg is not None and tribunal_cfg.requires_mtls:
            fetched = _fetch_mni_mtls(
                numero_cnj=numero_cnj,
                tribunal_cfg=tribunal_cfg,
                cpf=cpf,
                senha=senha,
                token_pin=token_pin,
            )
        else:
            auth = PasswordAuth(cpf=cpf, senha=senha)
            client = get_mni_client(tribunal_id, auth)
            response = consultar_processo(
                client=client,
                id_consultante=cpf,
                senha_consultante=senha,
                numero_cnj=numero_cnj,
                com_documentos=False,
            )

            sucesso = getattr(response, "sucesso", None)
            if sucesso is False:
                msg = getattr(response, "mensagem", "Unknown error")
                circuit_breaker.record_failure(tribunal_id)
                return DiffResult(
                    numero_cnj=numero_cnj,
                    tribunal_id=tribunal_id,
                    error=f"MNI error: {msg}",
                )

            fetched = parse_processo(response, tribunal_id=tribunal_id)

        circuit_breaker.record_success(tribunal_id)

        return diff_processo(
            fetched=fetched,
            last_sync_at=last_sync_at,
            known_movimento_keys=known_movimento_keys,
            known_doc_ids=known_doc_ids,
        )

    except Exception as e:
        circuit_breaker.record_failure(tribunal_id)
        logger.error("sync_processo_error", numero_cnj=numero_cnj, error=str(e))
        return DiffResult(
            numero_cnj=numero_cnj,
            tribunal_id=tribunal_id,
            error=f"{type(e).__name__}: {e}",
        )


def _fetch_mni_mtls(
    numero_cnj: str,
    tribunal_cfg: Any,
    cpf: str,
    senha: str,
    token_pin: str | None = None,
) -> ProcessoDomain:
    """Fetch a processo from an mTLS tribunal via the A3 token (PKCS#11).

    Thin adapter over :func:`juris.mni.fetch.fetch_processo_mni` — the shared
    helper the demo pipeline also uses, so both paths read mTLS tribunals
    through the same validated code. The token PIN comes from ``token_pin``
    (interactive caller) or, unattended, from ``settings.token_pin``; if
    neither is set the helper raises so the caller records a per-processo
    failure rather than crashing.

    Args:
        numero_cnj: Case number.
        tribunal_cfg: TribunalConfig for the mTLS tribunal.
        cpf: Consultant CPF (idConsultante).
        senha: PJe application password (senhaConsultante).
        token_pin: Token PIN; falls back to settings.token_pin when None.

    Returns:
        The fetched :class:`ProcessoDomain`.

    Raises:
        RuntimeError: If no token PIN is available or MNI returns an error.
    """
    from juris.mni.fetch import fetch_processo_mni

    return fetch_processo_mni(numero_cnj, tribunal_cfg, cpf, senha, token_pin=token_pin)


async def sync_processo_datajud(
    numero_cnj: str,
    tribunal_id: str,
    last_sync_at: datetime | None = None,
    known_movimento_keys: set[tuple] | None = None,
    known_doc_ids: set[str] | None = None,
) -> DiffResult:
    """Sync a single processo via DataJud (fallback for broken MNI tribunals).

    Args:
        numero_cnj: Case number.
        tribunal_id: Tribunal identifier.
        last_sync_at: Last sync timestamp.
        known_movimento_keys: Existing movement keys.
        known_doc_ids: Existing document IDs.

    Returns:
        DiffResult with detected changes.
    """
    from juris.datajud.client import consultar_processo
    from juris.datajud.parser import parse_datajud_processo

    try:
        source = consultar_processo(numero_cnj, tribunal_id)
        if source is None:
            return DiffResult(
                numero_cnj=numero_cnj,
                tribunal_id=tribunal_id,
                error="Not found in DataJud",
            )

        fetched = parse_datajud_processo(source)
        return diff_processo(
            fetched=fetched,
            last_sync_at=last_sync_at,
            known_movimento_keys=known_movimento_keys,
            known_doc_ids=known_doc_ids,
        )

    except Exception as e:
        logger.error("sync_datajud_error", numero_cnj=numero_cnj, error=str(e))
        return DiffResult(
            numero_cnj=numero_cnj,
            tribunal_id=tribunal_id,
            error=f"DataJud: {type(e).__name__}: {e}",
        )


# Tribunals where MNI is broken and DataJud should be used
# Tribunals to read via DataJud first (no working MNI). TJMG used to be here
# as a stopgap; now that mTLS via the A3 token works it goes through MNI first,
# with DataJud still available as the on-error fallback inside run_nightly_single.
_DATAJUD_FALLBACK_TRIBUNALS: set[str] = set()


async def run_overnight_sync(
    processos: list[dict[str, Any]],
    cpf: str,
    senha: str,
    max_concurrent: int = 10,
) -> SyncSummary:
    """Run the overnight differential sync for all tracked processos.

    Args:
        processos: List of dicts with keys: numero_cnj, tribunal_id,
                   last_sync_at (datetime|None), known_movimento_keys (set),
                   known_doc_ids (set).
        cpf: Lawyer's CPF for MNI auth.
        senha: Password for MNI auth.
        max_concurrent: Maximum number of concurrent sync operations.

    Returns:
        SyncSummary with results for all processos.
    """
    correlation_id = new_correlation_id()
    logger.info(
        "overnight_sync_start",
        correlation_id=correlation_id,
        processos_count=len(processos),
        max_concurrent=max_concurrent,
    )

    summary = SyncSummary()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _sync_one(proc: dict[str, Any]) -> DiffResult:
        """Sync a single processo with semaphore-based concurrency control."""
        numero_cnj = proc["numero_cnj"]
        tribunal_id = proc["tribunal_id"]
        last_sync = proc.get("last_sync_at")
        known_movs = proc.get("known_movimento_keys", set())
        known_docs = proc.get("known_doc_ids", set())

        async with semaphore:
            if tribunal_id in _DATAJUD_FALLBACK_TRIBUNALS:
                result = await sync_processo_datajud(
                    numero_cnj, tribunal_id, last_sync, known_movs, known_docs,
                )
            else:
                result = await sync_processo_mni(
                    numero_cnj, tribunal_id, cpf, senha, last_sync, known_movs, known_docs,
                )
                # Auto-fallback: if MNI failed, try DataJud
                if result.error:
                    logger.warning(
                        "mni_failed_trying_datajud",
                        numero_cnj=numero_cnj,
                        tribunal=tribunal_id,
                        mni_error=result.error,
                    )
                    datajud_result = await sync_processo_datajud(
                        numero_cnj, tribunal_id, last_sync, known_movs, known_docs,
                    )
                    if not datajud_result.error:
                        result = datajud_result

            return result

    tasks = [_sync_one(proc) for proc in processos]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        summary.processos_checked += 1
        if isinstance(r, Exception):
            summary.processos_failed += 1
            summary.errors.append(f"Unexpected: {type(r).__name__}: {r}")
            continue

        summary.results.append(r)
        if r.error:
            summary.processos_failed += 1
            summary.errors.append(r.summary)
        elif r.had_changes:
            summary.processos_updated += 1
            summary.new_movimentos_total += len(r.new_movimentos)
            summary.new_documentos_total += len(r.new_documento_ids)

    summary.finish()

    logger.info(
        "overnight_sync_done",
        correlation_id=correlation_id,
        checked=summary.processos_checked,
        updated=summary.processos_updated,
        failed=summary.processos_failed,
        new_movs=summary.new_movimentos_total,
        duration_s=f"{summary.duration_seconds:.1f}",
    )

    return summary


def main() -> None:
    """CLI entry point for cron/systemd. Reads processos from LocalDB and runs sync."""
    import os
    import sys

    from juris.core.observability import setup_logging
    from juris.persistence.local_db import LocalDB

    setup_logging(log_level="INFO", json_output=True)
    logger.info("overnight_sync_cron_start")

    cpf = os.environ.get("JURIS_CPF", "")
    senha = os.environ.get("JURIS_SENHA", "")

    if not cpf or not senha:
        logger.error("overnight_sync_missing_credentials", hint="Set JURIS_CPF and JURIS_SENHA env vars")
        sys.exit(1)

    db = LocalDB()
    all_processos = db.get_all_processos()

    if not all_processos:
        logger.info("overnight_sync_no_processos", message="No processos tracked in LocalDB")
        sys.exit(0)

    processos: list[dict[str, Any]] = []
    for p in all_processos:
        known_keys = db.get_known_movimento_keys(p.id)
        last_sync = db.get_last_sync(p.numero_cnj)
        processos.append({
            "numero_cnj": p.numero_cnj,
            "tribunal_id": p.tribunal_id,
            "last_sync_at": last_sync,
            "known_movimento_keys": known_keys,
            "known_doc_ids": set(),
        })

    logger.info("overnight_sync_loaded", processos_count=len(processos))
    summary = asyncio.run(run_overnight_sync(processos, cpf, senha))

    logger.info(
        "overnight_sync_finished",
        checked=summary.processos_checked,
        updated=summary.processos_updated,
        failed=summary.processos_failed,
        duration_s=f"{summary.duration_seconds:.1f}",
    )

    sys.exit(1 if summary.processos_failed > 0 else 0)


if __name__ == "__main__":
    main()
