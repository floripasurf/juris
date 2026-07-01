"""Service layer for local web demo runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from juris.core.types import NumeroCNJ
from juris.demo import DemoRequest, OutputMode, SourceMode, run_demo
from juris.demo.artifacts import write_artifacts
from juris.demo.disclaimer import output_dir_name
from juris.demo.orchestrator import derive_demo_mode, load_processo
from juris.repertory.peticoes.models import TipoPeticao
from juris.web.jsonutil import ensure_list

if TYPE_CHECKING:
    from juris.llm.base import AbstractLLM
    from juris.repertory.retrieval.service import RepertoryService


class DemoRunError(Exception):
    """Raised when a local web demo run cannot be completed.

    ``message`` is safe to serialize to the browser. ``internal_detail`` is for
    logs only and may include local paths, dependency errors, or transport text.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "demo_run_failed",
        internal_detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.internal_detail = internal_detail or message


@dataclass(frozen=True, slots=True)
class WebDemoRunRequest:
    """Validated request used by the local web service."""

    numero_cnj: str
    tipo: str
    tribunal: str = "tjmg"
    source: str = "fixture"
    modo: str = "rascunho-pesquisa"
    out_root: Path = Path("juris-out")
    thesis: str | None = None
    instructions: str = ""
    cloud: bool = False
    skip_review: bool = False
    use_cache: bool = True
    tenant_id: str = "public"  # routes source=mni to this firm's agent (multi-tenant)
    cpf: str | None = None  # co-located MNI; in remote mode the agent resolves it


@dataclass(frozen=True, slots=True)
class WebDemoArtifact:
    """Artifact metadata and preview content for the local UI."""

    name: str
    path: str
    sha256: str
    preview: str


@dataclass(frozen=True, slots=True)
class WebDemoRun:
    """Web-facing summary of a completed demo run."""

    succeeded: bool
    degraded: bool
    degradation_reason: str
    errors: tuple[str, ...]
    duration_seconds: float
    output_dir: str
    artifacts: tuple[WebDemoArtifact, ...]
    estrategia: dict[str, object] | None = None  # the selected argumentative line (Relatório)
    review: dict[str, object] | None = None  # structured reviewer report
    grounding: dict[str, object] | None = None  # anti-hallucination state (verified/blocked)


def estrategia_payload(draft: object) -> dict[str, object] | None:
    """Extract the UI-facing strategy from a DraftResult (or None).

    Surfaces the chosen argumentative line, the runners-up, the deontological
    flags and the mandatory-review flag — the structured intelligence the
    operator console renders instead of burying it in markdown.
    """
    est = getattr(draft, "estrategia", None)
    if est is None:
        return None

    def _linha(linha: object) -> dict[str, object]:
        return {
            "tese": getattr(linha, "tese", ""),
            "ordem": getattr(linha, "ordem", ""),
            "confianca": getattr(linha, "confianca", ""),
            "score": getattr(linha, "score", 0.0),
            "fundamentos": list(getattr(linha, "fundamentos", [])),
            "citacoes": list(getattr(linha, "citacoes", [])),
            "riscos": list(getattr(linha, "riscos", [])),
            "fundamento_consequencialista": getattr(linha, "fundamento_consequencialista", None),
        }

    def _tom_minuta(confianca: str, *, revisao_obrigatoria: bool) -> str:
        # Firmeza proporcional à solidez; revisão obrigatória ⇒ não protocolar (só rascunho).
        if revisao_obrigatoria:
            return "não protocolar"
        return {
            "alta": "forte",
            "media": "cauteloso",
            "baixa": "rascunho",
        }.get(confianca, "cauteloso")

    def _matriz(item: object) -> dict[str, object]:
        return {
            "alegacao": getattr(item, "alegacao", ""),
            "provas": list(getattr(item, "provas", [])),
            "lacunas": list(getattr(item, "lacunas", [])),
        }

    matriz = [_matriz(i) for i in getattr(est, "matriz_probatoria", [])]
    lacunas_prova = [
        {
            "alegacao": str(item.get("alegacao") or ""),
            "lacunas": ensure_list(item.get("lacunas")) or ["sem prova indicada"],
        }
        for item in matriz
        if not item.get("provas") or item.get("lacunas")
    ]
    escolhida = _linha(est.escolhida)
    return {
        "escolhida": escolhida,
        "alternativas": [_linha(a) for a in getattr(est, "alternativas", [])],
        "avisos_deontologicos": list(getattr(est, "avisos_deontologicos", [])),
        "revisao_humana_obrigatoria": bool(getattr(est, "revisao_humana_obrigatoria", False)),
        "tom_minuta": _tom_minuta(
            str(escolhida.get("confianca") or ""),
            revisao_obrigatoria=bool(getattr(est, "revisao_humana_obrigatoria", False)),
        ),
        "classificacao": [
            {
                "texto": getattr(item, "texto", ""),
                "tipo": getattr(item, "tipo", ""),
            }
            for item in getattr(est, "classificacao", [])
        ],
        "matriz_probatoria": matriz,
        "lacunas_prova": lacunas_prova,
    }


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def grounding_payload(draft: object) -> dict[str, object] | None:
    """Extract the anti-hallucination state from a DraftResult (or None).

    Surfaces the grounding status, whether the draft was blocked, and the offending
    references — so the console renders the block as a first-class chip instead of
    leaving the operator to discover it in the markdown/manifest.
    """
    report = getattr(draft, "grounding_report", None)
    if report is None:
        return None
    return {
        "status": report.status.value,
        "blocked": not report.is_verified,
        "blocked_reason": getattr(draft, "blocked_reason", None),
        "failed_citation_ids": list(report.failed_citation_ids),
        "spurious_citations": list(report.spurious_citations),
    }


def review_payload(draft: object) -> dict[str, object] | None:
    """Extract the structured reviewer report from a DraftResult (or None).

    Surfaces the issues (by dimension/severity), the per-severity counts, and the
    verified citations — so the console shows the review as UI, not markdown.
    """
    rep = getattr(draft, "reviewer_report", None)
    if rep is None:
        return None

    issues = [
        {
            "dimension": _enum_value(getattr(i, "dimension", "")),
            "severity": _enum_value(getattr(i, "severity", "")),
            "title": getattr(i, "title", ""),
            "description": getattr(i, "description", ""),
            "suggestion": getattr(i, "suggestion", None),
            "line_anchor": getattr(i, "line_anchor", None),
            "citations": list(getattr(i, "citations", [])),
        }
        for i in getattr(rep, "issues", [])
    ]
    counts = {
        sev: sum(1 for i in issues if i["severity"] == sev)
        for sev in ("critical", "important", "suggestion")
    }
    citations = [
        {
            "raw": getattr(c, "raw_text", ""),
            "normalized": getattr(c, "normalized", ""),
            "found": bool(getattr(c, "found_in_repertory", False)),
        }
        for c in getattr(rep, "citations_found", [])
    ]
    return {"issues": issues, "counts": counts, "citations": citations}


async def execute_demo_run(request: WebDemoRunRequest) -> WebDemoRun:
    """Run the existing demo pipeline and return UI-ready artifact previews."""
    numero_cnj, tipo_peticao, source_mode, output_mode = _validate_request(request)
    is_demo_mode = derive_demo_mode(source_mode)

    repertory_path = _resolve_repertory_for_source(is_demo_mode)
    case_dir = request.out_root / output_dir_name(numero_cnj, demo_mode=is_demo_mode)
    case_dir.mkdir(parents=True, exist_ok=True)
    audit_path = case_dir / "audit.jsonl"

    llm = _build_llm(use_cloud=request.cloud)
    repertory = _build_repertory(repertory_path)

    try:
        processo = load_processo(
            numero_cnj,
            request.tribunal,
            source_mode,
            use_cache=request.use_cache,
            audit_path=audit_path,
            cpf=request.cpf,
            tenant_id=request.tenant_id,  # source=mni routes to the tenant's agent
        )
    except (LookupError, NotImplementedError, ValueError) as exc:
        raise DemoRunError(
            "Falha ao carregar o processo. Verifique CNJ, tribunal e origem selecionada.",
            code="process_load_failed",
            internal_detail=str(exc),
        ) from exc
    except (RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
        # Missing tenant binding, agent unavailable, or remote transport failure —
        # an operational problem, not a 500. Surface it as a controlled message.
        raise DemoRunError(
            "Falha ao consultar o agente/MNI. Verifique se o agente local está configurado e conectado.",
            code="agent_mni_failed",
            internal_detail=str(exc),
        ) from exc

    demo_request = DemoRequest(
        numero_cnj=numero_cnj,
        tipo_peticao=tipo_peticao,
        tribunal=request.tribunal,
        source=source_mode,
        out_root=request.out_root,
        thesis=request.thesis,
        instructions=request.instructions,
        use_cloud_llm=request.cloud,
        skip_review=request.skip_review,
        output_mode=output_mode,
    )

    try:
        result = await run_demo(
            demo_request,
            llm=llm,
            repertory=repertory,
            out_dir=case_dir,
            audit_path=audit_path,
            is_demo_mode=is_demo_mode,
            processo=processo,
            tenant_id=request.tenant_id,  # scope corpus to this firm (+ public seed)
        )
    except Exception as exc:  # noqa: BLE001
        raise DemoRunError(
            "Falha no pipeline demo. Verifique logs do servidor para diagnóstico.",
            code="demo_pipeline_failed",
            internal_detail=str(exc),
        ) from exc

    artifact_hashes = write_artifacts(result)
    artifacts = tuple(_artifact_preview(case_dir, name, sha256) for name, sha256 in sorted(artifact_hashes.items()))
    return WebDemoRun(
        succeeded=result.succeeded,
        degraded=result.degraded,
        degradation_reason=result.degradation_reason,
        errors=tuple(result.errors),
        duration_seconds=result.duration_seconds,
        output_dir=_relative_key(case_dir, request.out_root),
        artifacts=artifacts,
        estrategia=estrategia_payload(getattr(result, "draft", None)),
        review=review_payload(getattr(result, "draft", None)),
        grounding=grounding_payload(getattr(result, "draft", None)),
    )


def _validate_request(
    request: WebDemoRunRequest,
) -> tuple[str, TipoPeticao, SourceMode, OutputMode]:
    try:
        NumeroCNJ(request.numero_cnj)
    except ValueError as exc:
        raise DemoRunError("Número CNJ inválido. Use o formato NNNNNNN-DD.AAAA.J.TT.OOOO.") from exc

    try:
        tipo_peticao = TipoPeticao(request.tipo)
    except ValueError as exc:
        valid = ", ".join(item.value for item in TipoPeticao)
        raise DemoRunError(f"Tipo de petição inválido. Opções: {valid}.") from exc

    try:
        source_mode = SourceMode(request.source)
    except ValueError as exc:
        raise DemoRunError("Origem inválida. Opções: datajud, mni, fixture.") from exc

    try:
        output_mode = OutputMode(request.modo)
    except ValueError as exc:
        valid = ", ".join(item.value for item in OutputMode)
        raise DemoRunError(f"Modo de saída inválido. Opções: {valid}.") from exc

    return request.numero_cnj, tipo_peticao, source_mode, output_mode


def _resolve_repertory_for_source(is_demo_mode: bool) -> Path:
    from juris.repertory.readiness import read_status, resolve_repertory_path

    repertory_path = resolve_repertory_path()
    if is_demo_mode:
        return repertory_path

    status = read_status(repertory_path)
    if not status.is_ready:
        raise DemoRunError(
            "Corpus não está pronto para uso real. Rode `juris repertory status` antes de usar DataJud/MNI."
        )
    return repertory_path


def _build_llm(*, use_cloud: bool) -> AbstractLLM:
    if use_cloud:
        from juris.config import get_settings
        from juris.core.deid_llm import cloud_safe_llm
        from juris.llm.claude import ClaudeLLM

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise DemoRunError("ANTHROPIC_API_KEY não configurada.")
        # ADR-0016: case PII (incl. names, via LeNER-Br) is removed before the
        # cloud model sees it; the gate fails closed. cloud_safe_llm is
        # structurally an AbstractLLM (complete + model_name).
        wrapped = cloud_safe_llm(ClaudeLLM(api_key=settings.anthropic_api_key.get_secret_value()))
        return cast("AbstractLLM", wrapped)

    from juris.llm.ollama import OllamaLLM

    return OllamaLLM()


def _build_repertory(repertory_path: Path) -> RepertoryService:
    try:
        from juris.repertory.embeddings import LegalEmbedder
        from juris.repertory.retrieval.hybrid import HybridRetriever
        from juris.repertory.retrieval.reranker import CrossEncoderReranker
        from juris.repertory.retrieval.service import RepertoryService
        from juris.repertory.vector_store import LocalFTSStore

        store = LocalFTSStore(repertory_path)
        retriever = HybridRetriever(
            dense_store=store,
            sparse_store=store,
            embedder=LegalEmbedder(),
            reranker=CrossEncoderReranker(),
        )
        return RepertoryService(retriever)
    except Exception as exc:  # noqa: BLE001
        raise DemoRunError(
            "Falha ao inicializar repertório. Verifique a configuração do corpus local.",
            code="repertory_init_failed",
            internal_detail=str(exc),
        ) from exc


def _artifact_preview(case_dir: Path, name: str, sha256: str) -> WebDemoArtifact:
    path = case_dir / name
    preview = ""
    if path.exists() and path.is_file():
        preview = path.read_text(encoding="utf-8", errors="replace")[:12000]
    return WebDemoArtifact(name=name, path=name, sha256=sha256, preview=preview)


def _relative_key(path: Path, root: Path) -> str:
    """Stable public key for a path under the tenant output root."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.resolve().relative_to(root.resolve()).as_posix()
