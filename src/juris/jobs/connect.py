"""Connect orchestration — import/update the lawyer's acervo from the token.

Shared by the CLI ``juris connect`` command and the web ``POST /api/connect``
endpoint so both behave identically. Credentials are passed in resolved (this
never prompts): the CLI resolves them at its edge, the web from the request.

Flow:
1. Pull pending avisos → add their processos to the tracked list (auto-grow).
2. Apply an optional seed of CNJs (the historical acervo).
3. Persist the tracked list.
4. Unless ``do_sync`` is False, run the differential nightly over the tracked
   list — a full import on first connect, post-last-load deltas afterwards,
   computing prazos/alerts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from juris.core.observability import get_logger
from juris.jobs.nightly import run_nightly
from juris.jobs.tracking import get_tracked, merge_tracked, parse_cnj_seed, set_tracked
from juris.mni.tribunais import TribunalConfig

if TYPE_CHECKING:
    from juris.jobs.nightly import NightlySummary
    from juris.mni.service import MNIReadService
    from juris.persistence.local_db import LocalDB

logger = get_logger(__name__)


@dataclass(slots=True)
class ConnectResult:
    """Outcome of a connect run."""

    avisos_added: int
    seed_added: int
    total_tracked: int
    first_time: bool
    sync: NightlySummary | None = None
    seed_errors: list[str] = field(default_factory=list)


async def run_connect(
    tribunal_cfg: TribunalConfig,
    cpf: str,
    senha: str,
    *,
    token_pin: str | None = None,
    seed_text: str | None = None,
    do_sync: bool = True,
    mni_service: MNIReadService | None = None,
    db: LocalDB | None = None,
    tenant_id: str = "public",
) -> ConnectResult:
    """Import/update the tracked acervo and (optionally) sync it. See module docs.

    When ``db`` is given (the tenant's store), the tracked list and the sync
    writes are scoped to it; otherwise they use the single-user defaults.
    ``tenant_id`` tags the remote agent's audit log for this firm.
    """
    if mni_service is None:
        from juris.mni.factory import get_mni_read_service

        mni_service = get_mni_read_service(tenant_id)

    tracked = get_tracked(db=db)
    first_time = not tracked

    # 1) Pending avisos → tracked list.
    avisos = mni_service.consultar_avisos(tribunal_cfg, cpf, senha, token_pin=token_pin)
    avisos_entries: list[dict[str, str]] = (
        [{"numero_cnj": a.numero_processo, "tribunal": tribunal_cfg.id} for a in avisos.avisos if a.numero_processo]
        if avisos.sucesso
        else []
    )
    tracked, avisos_added = merge_tracked(tracked, avisos_entries)

    # 2) Optional seed of the historical acervo.
    seed_added = 0
    seed_errors: list[str] = []
    if seed_text:
        entries, seed_errors = parse_cnj_seed(seed_text, default_tribunal=tribunal_cfg.id)
        tracked, seed_added = merge_tracked(tracked, entries)
        if seed_errors:
            logger.warning(
                "connect_seed_invalid_lines",
                count=len(seed_errors),
                lines=seed_errors,
            )

    set_tracked(tracked, db=db)

    # 3) Differential import/update (handles first-time vs. delta itself).
    summary: NightlySummary | None = None
    if do_sync and tracked:
        # Thread the same MNIReadService into the nightly sync so a remote service
        # keeps the mTLS read at the agent — never a local read in the cloud (ADR-0015).
        summary = await run_nightly(
            tracked, cpf=cpf, senha=senha, token_pin=token_pin, db=db, mni_service=mni_service
        )

    return ConnectResult(
        avisos_added=avisos_added,
        seed_added=seed_added,
        total_tracked=len(tracked),
        first_time=first_time,
        sync=summary,
        seed_errors=seed_errors,
    )
