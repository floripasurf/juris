"""Unified nightly pipeline — differential sync -> persist -> analyze -> prazos -> alerts.

Bridges the overnight sync engine (MNI/DataJud differential read) with the
analysis pipeline (TPU classification, prazo computation, alert generation).
Works with LocalDB (SQLite) for single-user dev mode.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from juris.agents.analyzer import ProcessoAnalysis, analyze_processo
from juris.alerts.deadline_alerts import AlertBatch, generate_alerts
from juris.core.observability import get_logger
from juris.jobs.overnight import (
    _DATAJUD_FALLBACK_TRIBUNALS,
    sync_processo_datajud,
    sync_processo_mni,
)
from juris.mni.operations.differential import DiffResult
from juris.persistence.local_db import LocalDB
from juris.prazo.engine import PrazoReport, compute_prazos

if TYPE_CHECKING:
    from juris.mni.service import MNIReadService

logger = get_logger(__name__)


@dataclass(slots=True)
class NightlyResult:
    """Result for a single processo in the nightly pipeline."""

    numero_cnj: str
    tribunal: str
    success: bool = False
    error: str | None = None
    new_movimentos: int = 0
    prazos_computed: int = 0
    critical_alerts: int = 0
    analysis: ProcessoAnalysis | None = None
    prazo_report: PrazoReport | None = None
    alert_batch: AlertBatch | None = None
    diff_result: DiffResult | None = None

    @property
    def summary(self) -> str:
        if self.error:
            return f"[FAIL] {self.numero_cnj}: {self.error}"
        parts = [f"{self.numero_cnj}"]
        if self.new_movimentos:
            parts.append(f"+{self.new_movimentos} mov")
        if self.prazos_computed:
            parts.append(f"{self.prazos_computed} prazos")
        if self.critical_alerts:
            parts.append(f"{self.critical_alerts} alertas")
        if not self.new_movimentos:
            parts.append("sem alteracoes")
        return " | ".join(parts)


@dataclass(slots=True)
class NightlySummary:
    """Batch summary for a nightly pipeline run."""

    results: list[NightlyResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    @property
    def total_critical_alerts(self) -> int:
        return sum(r.critical_alerts for r in self.results)

    @property
    def duration_seconds(self) -> float:
        if not self.finished_at:
            return 0
        return (self.finished_at - self.started_at).total_seconds()


def _fetch_full_processo(numero_cnj: str, tribunal: str) -> Any:
    """Fetch full processo from DataJud for analysis after diff detects changes."""
    from juris.datajud.client import consultar_processo
    from juris.datajud.parser import parse_datajud_processo

    source = consultar_processo(numero_cnj, tribunal)
    if source is None:
        return None
    return parse_datajud_processo(source)


async def run_nightly_single(
    numero_cnj: str,
    tribunal: str,
    db: LocalDB,
    cpf: str,
    senha: str,
    today: date | None = None,
    token_pin: str | None = None,
    mni_service: MNIReadService | None = None,
) -> NightlyResult:
    """Run the nightly pipeline for a single processo.

    Flow:
    1. Differential check via MNI/DataJud (overnight sync)
    2. If no changes: log and return early
    3. If changes detected: fetch full processo -> persist -> analyze -> prazos -> alerts

    Args:
        numero_cnj: CNJ case number.
        tribunal: Tribunal identifier.
        db: LocalDB instance.
        cpf: Lawyer's CPF for MNI auth.
        senha: Password for MNI auth.
        today: Override current date (for testing).

    Returns:
        NightlyResult with pipeline output.
    """
    result = NightlyResult(numero_cnj=numero_cnj, tribunal=tribunal)
    today = today or date.today()

    # 1. Get processo state from LocalDB
    existing = db.get_processo_by_cnj(numero_cnj)
    last_sync_at = db.get_last_sync(numero_cnj) if existing else None
    known_keys = db.get_known_movimento_keys(existing.id) if existing else set()

    # 2. Differential sync — detect if anything changed
    if tribunal in _DATAJUD_FALLBACK_TRIBUNALS:
        diff = await sync_processo_datajud(
            numero_cnj, tribunal, last_sync_at, known_keys,
        )
        source = "datajud"
    else:
        diff = await sync_processo_mni(
            numero_cnj, tribunal, cpf, senha, last_sync_at, known_keys,
            token_pin=token_pin,
            mni_service=mni_service,
        )
        source = "mni"
        if diff.error:
            logger.warning(
                "nightly_mni_fallback",
                numero_cnj=numero_cnj,
                mni_error=diff.error,
            )
            diff = await sync_processo_datajud(
                numero_cnj, tribunal, last_sync_at, known_keys,
            )
            source = "datajud"

    result.diff_result = diff

    # 3. Handle sync error
    if diff.error:
        result.error = diff.error
        db.log_sync(numero_cnj, tribunal, source, success=False, error=diff.error)
        return result

    # 4. No changes — log and return early
    if not diff.had_changes:
        db.log_sync(numero_cnj, tribunal, source, success=True, had_changes=False)
        result.success = True
        return result

    # 5. Changes detected — get the full processo for complete analysis.
    # Reuse the processo already fetched during the diff (MNI/mTLS carries it);
    # only fall back to a DataJud fetch when the diff didn't include one.
    processo = diff.fetched
    if processo is None:
        try:
            processo = await asyncio.to_thread(_fetch_full_processo, numero_cnj, tribunal)
        except Exception as e:  # noqa: BLE001
            result.error = f"Full fetch failed: {type(e).__name__}: {e}"
            db.log_sync(numero_cnj, tribunal, source, success=False, error=result.error)
            return result

    if processo is None:
        result.error = "Full fetch returned None"
        db.log_sync(numero_cnj, tribunal, source, success=False, error=result.error)
        return result

    # 6a. Persist processo + new movimentos
    processo_id = db.upsert_processo(
        numero_cnj=processo.numero_cnj,
        tribunal_id=tribunal,
        classe=processo.classe,
        assunto=processo.assunto,
        valor_causa=processo.valor_causa,
        orgao_julgador=processo.orgao_julgador,
    )

    mov_dicts = [
        {
            "data_hora": m.data_hora,
            "tipo": m.tipo,
            "codigo_nacional": m.codigo_nacional,
            "complemento": m.complemento,
            "descricao": m.descricao,
            "id_movimento": m.id_movimento,
            "categoria_semantica": None,
        }
        for m in processo.movimentos
    ]
    new_count = db.insert_movimentos(processo_id, mov_dicts)
    result.new_movimentos = new_count

    # 6b. Analyze ALL movements (full analysis for accurate prazos)
    analysis = await analyze_processo(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        movimentos=processo.movimentos,
    )
    result.analysis = analysis

    # 6c. Compute prazos
    report = compute_prazos(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        analyses=analysis.analyzed,
        today=today,
    )
    result.prazo_report = report
    result.prazos_computed = len(report.prazos)

    # 6d. Persist prazos
    for prazo in report.prazos:
        db.upsert_prazo(
            processo_id=processo_id,
            numero_cnj=prazo.numero_cnj,
            rule_nome=prazo.rule.nome,
            data_inicio=datetime.combine(prazo.data_inicio, datetime.min.time(), tzinfo=UTC),
            data_limite=datetime.combine(prazo.data_limite, datetime.min.time(), tzinfo=UTC),
            dias_uteis_total=prazo.dias_uteis_total,
            status=prazo.status.value,
            urgencia=prazo.urgencia.value,
            tipo_acao=prazo.rule.tipo_acao.value,
            categoria=prazo.categoria.value,
            rule_base_legal=prazo.rule.base_legal,
        )

    # 6e. Generate alerts
    alerts = generate_alerts(report)
    result.alert_batch = alerts
    result.critical_alerts = alerts.critical_count

    # 7. Log sync
    db.log_sync(
        numero_cnj=numero_cnj,
        tribunal_id=tribunal,
        source=source,
        success=True,
        had_changes=True,
        new_movimentos=new_count,
    )

    result.success = True
    logger.info(
        "nightly_single_done",
        numero_cnj=numero_cnj,
        new_movs=new_count,
        prazos=len(report.prazos),
        critical_alerts=alerts.critical_count,
    )
    return result


async def run_nightly(
    processos: list[dict[str, str]],
    db: LocalDB | None = None,
    cpf: str = "",
    senha: str = "",
    max_concurrent: int = 10,
    today: date | None = None,
    token_pin: str | None = None,
    mni_service: MNIReadService | None = None,
) -> NightlySummary:
    """Run the nightly pipeline for a batch of processos with concurrency control.

    Args:
        processos: List of dicts with keys: numero_cnj, tribunal.
        db: LocalDB instance (creates default if None).
        cpf: Lawyer's CPF for MNI auth.
        senha: Password for MNI auth.
        max_concurrent: Maximum concurrent processo pipelines.
        today: Override current date (for testing).

    Returns:
        NightlySummary with all results.
    """
    db = db or LocalDB()
    summary = NightlySummary()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_one(proc: dict[str, str]) -> NightlyResult:
        async with semaphore:
            return await run_nightly_single(
                numero_cnj=proc["numero_cnj"],
                tribunal=proc.get("tribunal", "tjmg"),
                db=db,
                cpf=cpf,
                senha=senha,
                today=today,
                token_pin=token_pin,
                mni_service=mni_service,
            )

    tasks = [_run_one(proc) for proc in processos]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, BaseException):
            err_result = NightlyResult(
                numero_cnj="unknown",
                tribunal="unknown",
                error=f"Unexpected: {type(r).__name__}: {r}",
            )
            summary.results.append(err_result)
        else:
            summary.results.append(r)

    summary.finished_at = datetime.now(UTC)

    logger.info(
        "nightly_batch_done",
        total=summary.total,
        succeeded=summary.succeeded,
        failed=summary.failed,
        critical_alerts=summary.total_critical_alerts,
        duration=f"{summary.duration_seconds:.1f}s",
    )

    return summary
