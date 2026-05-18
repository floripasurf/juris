"""End-to-end demo orchestrator.

Calls internal services directly (no CLI shell-out) so artifact capture is
structured and testable. Used by the `juris demo` command and by integration
tests.

Flow:
    1. Load processo (DataJud or fixture)
    2. Analyze movements (rule-based, optional LLM)
    3. Compute prazos
    4. Draft petition (research + verify + review)
    5. Write artifacts (handled by `juris.demo.artifacts`)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from juris.agents.analyzer import ProcessoAnalysis, analyze_processo
from juris.agents.citation_verifier import MarkerCitationVerifier
from juris.agents.drafter import DrafterAgent, DraftRequest, DraftResult
from juris.agents.researcher import Researcher
from juris.core.observability import get_logger
from juris.defesas.analyzer import DefesaAnalyzer
from juris.defesas.context import ProcessoContext
from juris.demo.output_mode import OutputMode
from juris.llm.base import AbstractLLM
from juris.mni.parsers.processo import ProcessoDomain
from juris.persistence.audit import AuditLog
from juris.prazo.engine import PrazoReport, compute_prazos
from juris.repertory.peticoes.models import TipoPeticao
from juris.repertory.retrieval.service import RepertoryService
from juris.review.reviewer import ReviewerAgent

logger = get_logger(__name__)


class SourceMode(str, Enum):
    """Source of processo data for the demo run."""

    DATAJUD = "datajud"
    MNI = "mni"  # not implemented — requires A3 token + tribunal creds
    FIXTURE = "fixture"  # in-memory fixture; forces DEMO mode


@dataclass(frozen=True, slots=True)
class DemoRequest:
    """Inputs for an end-to-end demo run."""

    numero_cnj: str
    tipo_peticao: TipoPeticao
    tribunal: str = "tjmg"
    cpf: str | None = None
    source: SourceMode = SourceMode.DATAJUD
    out_root: Path = Path("juris-out")
    thesis: str | None = None
    instructions: str = ""
    use_cloud_llm: bool = False
    skip_review: bool = False
    use_llm_for_analysis: bool = False
    output_mode: OutputMode = OutputMode.MINUTA_SUGERIDA


@dataclass(slots=True)
class DemoResult:
    """Output of a demo run.

    The orchestrator returns this in-memory; the artifacts module is what
    actually persists files. This separation makes the orchestrator unit-
    testable without touching the filesystem.
    """

    request: DemoRequest
    processo: ProcessoDomain
    out_dir: Path
    is_demo_mode: bool
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    audit_log_path: Path
    analysis: ProcessoAnalysis | None = None
    prazo_report: PrazoReport | None = None
    draft: DraftResult | None = None
    errors: list[str] = field(default_factory=list)
    llm_model_used: str = ""

    @property
    def succeeded(self) -> bool:
        return self.draft is not None and not self.errors


class DemoOrchestrator:
    """Internal orchestrator. Public entry point is `run_demo()`."""

    def __init__(
        self,
        *,
        llm: AbstractLLM,
        repertory: RepertoryService,
        audit: AuditLog,
        analysis_llm: AbstractLLM | None = None,
    ) -> None:
        self._llm = llm
        self._repertory = repertory
        self._audit = audit
        self._analysis_llm = analysis_llm

    async def run(
        self,
        request: DemoRequest,
        *,
        processo: ProcessoDomain,
        out_dir: Path,
        is_demo_mode: bool,
    ) -> DemoResult:
        """Execute the full demo pipeline end-to-end.

        The processo is passed in (not fetched here) so the source-loading
        concern is testable in isolation. See `load_processo()`.
        """
        started = datetime.now(UTC)
        t0 = time.monotonic()

        result = DemoResult(
            request=request,
            processo=processo,
            out_dir=out_dir,
            is_demo_mode=is_demo_mode,
            started_at=started,
            finished_at=started,
            duration_seconds=0.0,
            audit_log_path=self._audit_path(),
            llm_model_used=self._llm.model_name,
        )

        self._audit.log(
            event_type="demo.started",
            actor="system",
            processo_cnj=processo.numero_cnj,
            details={
                "tipo_peticao": request.tipo_peticao.value,
                "tribunal": request.tribunal,
                "source": request.source.value,
                "demo_mode": is_demo_mode,
                "output_mode": request.output_mode.value,
                "out_dir": str(out_dir),
            },
        )

        # Step 1: analyze movements
        try:
            result.analysis = await analyze_processo(
                numero_cnj=processo.numero_cnj,
                tribunal=request.tribunal,
                movimentos=processo.movimentos,
                llm=self._analysis_llm if request.use_llm_for_analysis else None,
            )
        except Exception as exc:  # noqa: BLE001 — surface but don't abort
            logger.warning("demo_analyze_failed", error=str(exc))
            result.errors.append(f"analyze: {exc}")

        # Step 2: compute prazos (only if analysis succeeded)
        if result.analysis is not None:
            try:
                result.prazo_report = compute_prazos(
                    numero_cnj=processo.numero_cnj,
                    tribunal=request.tribunal,
                    analyses=result.analysis.analyzed,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("demo_prazos_failed", error=str(exc))
                result.errors.append(f"prazos: {exc}")

        # Step 3: draft petition
        try:
            result.draft = await self._run_drafter(request, processo)
        except Exception as exc:  # noqa: BLE001
            if _can_degrade_to_deterministic_rascunho(request, exc):
                logger.warning("demo_rascunho_deterministic_fallback", error=str(exc))
                result.draft = _build_deterministic_rascunho_draft(
                    request=request,
                    processo=processo,
                    analysis=result.analysis,
                )
                self._audit.log(
                    event_type="demo.rascunho_deterministic_fallback",
                    actor="system",
                    processo_cnj=processo.numero_cnj,
                    details={
                        "reason": str(exc),
                        "output_mode": request.output_mode.value,
                    },
                )
            else:
                logger.warning("demo_draft_failed", error=str(exc))
                result.errors.append(f"draft: {exc}")

        result.finished_at = datetime.now(UTC)
        result.duration_seconds = time.monotonic() - t0

        self._audit.log(
            event_type="demo.finished",
            actor="system",
            processo_cnj=processo.numero_cnj,
            details={
                "duration_seconds": result.duration_seconds,
                "succeeded": result.succeeded,
                "errors": result.errors,
                "output_mode": request.output_mode.value,
                "draft_revisions": result.draft.revisions if result.draft else None,
                "prazos_count": len(result.prazo_report.prazos) if result.prazo_report else 0,
                "actionable_count": (len(result.analysis.actionable) if result.analysis else 0),
            },
        )
        return result

    async def _run_drafter(
        self,
        request: DemoRequest,
        processo: ProcessoDomain,
    ) -> DraftResult:
        """Wire and run the DrafterAgent against the resolved processo."""
        researcher = Researcher(repertory=self._repertory, llm=self._llm, audit=self._audit)
        verifier = MarkerCitationVerifier(repertory=self._repertory)
        defesa_analyzer = DefesaAnalyzer(llm=self._llm)
        reviewer: ReviewerAgent | None = None
        if not request.skip_review:
            reviewer = ReviewerAgent(llm=self._llm, retriever=self._repertory, audit_log=self._audit)

        agent = DrafterAgent(
            llm=self._llm,
            repertory=self._repertory,
            researcher=researcher,
            verifier=verifier,
            reviewer=reviewer,
            audit=self._audit,
            defesa_analyzer=defesa_analyzer,
        )

        context = ProcessoContext(
            numero_cnj=processo.numero_cnj,
            tribunal=request.tribunal,
            classe=processo.classe or "",
            assuntos=[processo.assunto] if processo.assunto else [],
            valor_causa=processo.valor_causa,
        )

        draft_req = DraftRequest(
            numero_cnj=processo.numero_cnj,
            tribunal=request.tribunal,
            tipo_peticao=request.tipo_peticao,
            thesis=request.thesis,
            custom_instructions=request.instructions,
            use_cloud_llm=request.use_cloud_llm,
        )
        return await agent.draft(draft_req, context)

    def _audit_path(self) -> Path:
        # AuditLog stores its path privately; reach in once via name-mangle-free attr.
        return getattr(self._audit, "_path", Path("audit.jsonl"))


def _can_degrade_to_deterministic_rascunho(request: DemoRequest, exc: Exception) -> bool:
    """Return True when RASCUNHO mode can complete without a live LLM.

    RASCUNHO DE PESQUISA is not a fileable petition. If the local LLM is
    unavailable, we can still produce a deterministic memo from DataJud,
    rule-based movement analysis and prazo computation instead of aborting.
    """
    if request.output_mode is not OutputMode.RASCUNHO_PESQUISA:
        return False
    message = str(exc).lower()
    return (
        "all connection attempts failed" in message
        or "connection refused" in message
        or "connecterror" in exc.__class__.__name__.lower()
    )


def _build_deterministic_rascunho_draft(
    *,
    request: DemoRequest,
    processo: ProcessoDomain,
    analysis: ProcessoAnalysis | None,
) -> DraftResult:
    """Build raw material for the rascunho artifact without any LLM call."""
    research_summary = (
        "Execução em modo determinístico sem LLM local/API. "
        "O memorando abaixo usa apenas dados públicos do DataJud, "
        "classificação TPU por regras e cálculo de prazos."
    )
    if analysis is not None:
        research_summary += f"\n\n{analysis.summary}"

    headings = [
        "# Rascunho determinístico",
        "",
        "## Contexto processual",
        f"- CNJ: {processo.numero_cnj}",
        f"- Tribunal: {request.tribunal}",
    ]
    if processo.classe:
        headings.append(f"- Classe: {processo.classe}")
    if processo.assunto:
        headings.append(f"- Assunto: {processo.assunto}")
    headings.extend(
        [
            "",
            "## Pontos para validação manual",
            "- Conferir os últimos movimentos diretamente no sistema do tribunal.",
            "- Confirmar a contagem de prazo antes de qualquer providência.",
            "- Redigir a peça manualmente com revisão de advogado(a).",
        ]
    )

    contraponto = (
        "Modo sem LLM: não houve geração de tese, pesquisa argumentativa ou "
        "contraponto jurisprudencial. Use este arquivo apenas como triagem "
        "operacional e ponto de partida para pesquisa manual."
    )
    return DraftResult(
        draft_markdown="\n".join(headings),
        contraponto_section=contraponto,
        citations_used=[],
        research_summary=research_summary,
    )


def load_processo(
    numero_cnj: str,
    tribunal: str,
    source: SourceMode,
    *,
    use_cache: bool = True,
    audit_path: Path | None = None,
) -> ProcessoDomain:
    """Resolve a ProcessoDomain from the configured source.

    DATAJUD: live lookup via DataJud public API.
    FIXTURE: synthetic in-memory processo for offline demos.
    MNI:     not implemented — raises NotImplementedError.
    """
    if source is SourceMode.DATAJUD:
        from juris.datajud.client import consultar_processo as datajud_consulta
        from juris.datajud.parser import parse_datajud_processo

        raw = datajud_consulta(numero_cnj, tribunal, use_cache=use_cache, audit_path=audit_path)
        if raw is None:
            msg = f"Processo {numero_cnj} não encontrado no DataJud ({tribunal})."
            raise LookupError(msg)
        return parse_datajud_processo(raw)

    if source is SourceMode.FIXTURE:
        return _build_fixture_processo(numero_cnj, tribunal)

    if source is SourceMode.MNI:
        msg = (
            "Source 'mni' ainda não implementado para o demo. Use 'datajud' (default) ou 'fixture' para teste offline."
        )
        raise NotImplementedError(msg)

    raise ValueError(f"Source desconhecido: {source}")


def _build_fixture_processo(numero_cnj: str, tribunal: str) -> ProcessoDomain:
    """Construct a synthetic processo for offline demos (DEMO mode only).

    The fixture intentionally includes a single CITACAO movement so the
    analyzer/prazo/draft pipeline has actionable input.
    """
    from juris.mni.parsers.processo import Movimento, Parte

    now = datetime.now(UTC)
    movimentos = [
        Movimento(
            data_hora=now,
            tipo="movimentoNacional",
            codigo_nacional=12265,  # citacao - high-confidence trigger
            descricao="Citação realizada (DEMO).",
            id_movimento="demo-mov-1",
        ),
    ]
    partes = [
        Parte(nome="Autor Demo", tipo="autor"),
        Parte(nome="Réu Demo", tipo="reu"),
    ]
    return ProcessoDomain(
        numero_cnj=numero_cnj,
        classe="Procedimento Comum Cível",
        assunto="Cobrança",
        valor_causa=10_000.00,
        tribunal=tribunal,
        movimentos=movimentos,
        partes=partes,
    )


async def run_demo(
    request: DemoRequest,
    *,
    llm: AbstractLLM,
    repertory: RepertoryService,
    out_dir: Path,
    audit_path: Path,
    is_demo_mode: bool,
    processo: ProcessoDomain | None = None,
    analysis_llm: AbstractLLM | None = None,
) -> DemoResult:
    """Top-level entry point. Loads processo (if not provided) and runs the
    pipeline.

    Callers (CLI) should use `juris.demo.artifacts.write_artifacts(result)`
    to persist the run.
    """
    if processo is None:
        processo = load_processo(request.numero_cnj, request.tribunal, request.source)

    audit = AuditLog(audit_path)
    orchestrator = DemoOrchestrator(
        llm=llm,
        repertory=repertory,
        audit=audit,
        analysis_llm=analysis_llm,
    )
    return await orchestrator.run(
        request,
        processo=processo,
        out_dir=out_dir,
        is_demo_mode=is_demo_mode,
    )


def derive_demo_mode(source: SourceMode) -> bool:
    """Centralized rule: fixture source ALWAYS forces demo mode.

    DataJud and MNI runs are real-mode (still get the disclaimer footer, but
    no DEMO banner / dir prefix).
    """
    return source is SourceMode.FIXTURE


def serialize_processo_summary(processo: ProcessoDomain) -> dict[str, Any]:
    """Build the case-summary payload for artifact output."""
    return {
        "numero_cnj": processo.numero_cnj,
        "classe": processo.classe,
        "assunto": processo.assunto,
        "valor_causa": processo.valor_causa,
        "tribunal": processo.tribunal,
        "orgao_julgador": processo.orgao_julgador,
        "grau": processo.grau,
        "data_ajuizamento": (processo.data_ajuizamento.isoformat() if processo.data_ajuizamento else None),
        "ultimo_movimento": (
            {
                "data_hora": processo.ultimo_movimento.data_hora.isoformat(),
                "descricao": processo.ultimo_movimento.descricao,
                "codigo_nacional": processo.ultimo_movimento.codigo_nacional,
            }
            if processo.ultimo_movimento
            else None
        ),
        "movimentos_count": len(processo.movimentos),
        "partes": [{"nome": p.nome, "tipo": p.tipo} for p in processo.partes],
    }
