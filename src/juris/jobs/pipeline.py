"""Full sync pipeline — fetch → analyze → compute prazos → persist → alert.

This is the main integration pipeline that ties all Sprint 1-4 components together.
Works in local mode (SQLite) without requiring PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from juris.agents.analyzer import ProcessoAnalysis, analyze_processo
from juris.alerts.deadline_alerts import AlertBatch, generate_alerts
from juris.config import get_settings
from juris.core.observability import get_logger
from juris.mni.parsers.processo import ProcessoDomain
from juris.persistence.local_db import LocalDB
from juris.prazo.engine import PrazoReport, compute_prazos

logger = get_logger(__name__)


@dataclass(slots=True)
class PipelineResult:
    """Result of a full sync pipeline run for a single processo."""

    numero_cnj: str
    tribunal: str
    success: bool = False
    error: str | None = None
    new_movimentos: int = 0
    total_movimentos: int = 0
    prazos_computed: int = 0
    critical_alerts: int = 0
    source: str = "datajud"
    analysis: ProcessoAnalysis | None = None
    prazo_report: PrazoReport | None = None
    alert_batch: AlertBatch | None = None

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
        return " | ".join(parts)


@dataclass(slots=True)
class PipelineSummary:
    """Summary of a full pipeline run across multiple processos."""

    results: list[PipelineResult] = field(default_factory=list)
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


def _fetch_processo(numero_cnj: str, tribunal: str) -> ProcessoDomain | None:
    """Fetch a processo from DataJud."""
    from juris.datajud.client import consultar_processo
    from juris.datajud.parser import parse_datajud_processo

    source = consultar_processo(numero_cnj, tribunal)
    if source is None:
        return None
    return parse_datajud_processo(source)


async def run_pipeline_single(
    numero_cnj: str,
    tribunal: str,
    db: LocalDB,
    today: date | None = None,
) -> PipelineResult:
    """Run the full pipeline for a single processo.

    Steps:
    1. Fetch from DataJud
    2. Persist processo + movimentos (dedup)
    3. Analyze movements (rule-first)
    4. Compute prazos
    5. Persist prazos
    6. Generate alerts
    7. Log sync
    """
    result = PipelineResult(numero_cnj=numero_cnj, tribunal=tribunal)
    today = today or date.today()

    # 1. Fetch
    try:
        processo = _fetch_processo(numero_cnj, tribunal)
    except Exception as e:  # noqa: BLE001
        result.error = f"Fetch failed: {type(e).__name__}: {e}"
        db.log_sync(numero_cnj, tribunal, "datajud", success=False, error=result.error)
        return result

    if processo is None:
        result.error = "Not found in DataJud"
        db.log_sync(numero_cnj, tribunal, "datajud", success=False, error=result.error)
        return result

    # 2. Persist processo + movimentos
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
    new_movs = db.insert_movimentos(processo_id, mov_dicts)
    result.new_movimentos = new_movs
    result.total_movimentos = len(processo.movimentos)

    # 3. Analyze
    analysis = await analyze_processo(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        movimentos=processo.movimentos,
    )
    result.analysis = analysis

    # 4. Compute prazos
    report = compute_prazos(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        analyses=analysis.analyzed,
        today=today,
        parte_representada=get_settings().parte_representada,
    )
    result.prazo_report = report
    result.prazos_computed = len(report.prazos)

    # 5. Persist prazos
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

    # 6. Generate alerts
    alerts = generate_alerts(report)
    result.alert_batch = alerts
    result.critical_alerts = alerts.critical_count

    # 7. Log sync
    db.log_sync(
        numero_cnj=numero_cnj,
        tribunal_id=tribunal,
        source="datajud",
        success=True,
        had_changes=new_movs > 0,
        new_movimentos=new_movs,
    )

    result.success = True
    logger.info(
        "pipeline_complete",
        numero_cnj=numero_cnj,
        new_movs=new_movs,
        prazos=len(report.prazos),
        alerts=alerts.critical_count,
    )
    return result


async def run_pipeline(
    processos: list[dict[str, str]],
    db: LocalDB | None = None,
    today: date | None = None,
) -> PipelineSummary:
    """Run the full pipeline for multiple processos.

    Args:
        processos: List of dicts with keys: numero_cnj, tribunal.
        db: Local database (creates default if None).
        today: Override current date (for testing).

    Returns:
        PipelineSummary with all results.
    """
    db = db or LocalDB()
    summary = PipelineSummary()

    for proc in processos:
        result = await run_pipeline_single(
            numero_cnj=proc["numero_cnj"],
            tribunal=proc.get("tribunal", "tjmg"),
            db=db,
            today=today,
        )
        summary.results.append(result)

    summary.finished_at = datetime.now(UTC)

    logger.info(
        "pipeline_batch_complete",
        total=summary.total,
        succeeded=summary.succeeded,
        failed=summary.failed,
        critical_alerts=summary.total_critical_alerts,
        duration=f"{summary.duration_seconds:.1f}s",
    )

    return summary
