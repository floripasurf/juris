"""Persist artifacts produced by a demo run.

All lawyer-visible markdown is wrapped via `juris.demo.disclaimer.wrap_document`
so the DEMO banner (fixture only), the mode banner, and the disclaimer
footer cannot be forgotten.

Artifacts written under the run's ``out_dir``:

    draft.md               # MINUTA SUGERIDA: petition draft (default mode)
    rascunho-pesquisa.md   # RASCUNHO DE PESQUISA: research memo (--modo flag)
    reviewer-report.md     # ReviewerAgent findings
    prazos.md              # deadline table
    case-summary.md        # processo metadata + analysis summary
    run-manifest.json      # run metadata + sha256 of each artifact
    audit.jsonl            # per-case audit chain (copied from log)
    audit-summary.md       # human-readable audit recap
    draft.contraponto.md   # MINUTA mode only — RASCUNHO folds contraponto
                           # into the memo's "Riscos / contraponto" section.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from juris.agents.analyzer import ProcessoAnalysis
from juris.agents.drafter import DraftResult
from juris.core.observability import get_logger
from juris.demo.disclaimer import wrap_document
from juris.demo.orchestrator import DemoResult, serialize_processo_summary
from juris.demo.output_mode import (
    OutputMode,
    banner_for,
    draft_filename,
    label_for,
)
from juris.demo.rascunho import build_rascunho_markdown
from juris.persistence.audit import AuditLog
from juris.prazo.engine import PrazoReport, StatusPrazo

logger = get_logger(__name__)


def write_artifacts(result: DemoResult) -> dict[str, str]:
    """Write all demo artifacts to disk and return {filename: sha256}.

    Returns an artifact -> sha256 map suitable for inclusion in run-manifest.
    """
    out = result.out_dir
    out.mkdir(parents=True, exist_ok=True)
    demo_mode = result.is_demo_mode
    output_mode = result.request.output_mode
    artifacts: dict[str, str] = {}

    # 1. Draft (MINUTA SUGERIDA) or Rascunho (RASCUNHO DE PESQUISA)
    if result.draft is not None:
        artifacts.update(
            _write_primary_output(
                out,
                result.draft,
                analysis=result.analysis,
                demo_mode=demo_mode,
                output_mode=output_mode,
            )
        )

    # 2. Reviewer report
    if result.draft and result.draft.reviewer_report is not None:
        artifacts.update(_write_reviewer_report(out, result.draft.reviewer_report, demo_mode=demo_mode))

    # 3. Prazos
    if result.prazo_report is not None:
        artifacts.update(_write_prazos(out, result.prazo_report, demo_mode=demo_mode))

    # 4. Case summary
    artifacts.update(_write_case_summary(out, result, demo_mode=demo_mode))

    # 5. Audit log + summary
    artifacts.update(_write_audit(out, result))

    # 6. Run manifest (must be last so it can include all sha256s)
    manifest_payload = _build_manifest(result, artifacts)
    manifest_path = out / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    artifacts["run-manifest.json"] = _sha256(manifest_path)

    return artifacts


# ---------------------------------------------------------------------------
# Primary output: MINUTA SUGERIDA (draft) or RASCUNHO DE PESQUISA (memo)
# ---------------------------------------------------------------------------


def _write_primary_output(
    out: Path,
    draft: DraftResult,
    *,
    analysis: ProcessoAnalysis | None,
    demo_mode: bool,
    output_mode: OutputMode,
) -> dict[str, str]:
    """Persist the run's primary lawyer-facing artifact.

    MINUTA mode writes the petition draft to ``draft.md`` (and the
    contraponto to a sibling file when present). RASCUNHO mode writes the
    research memo to ``rascunho-pesquisa.md`` instead — the contraponto is
    folded into the memo's "Riscos / contraponto" section.
    """
    if output_mode is OutputMode.RASCUNHO_PESQUISA:
        return _write_rascunho(out, draft, analysis=analysis, demo_mode=demo_mode)
    return _write_minuta(out, draft, demo_mode=demo_mode)


def _write_minuta(out: Path, draft: DraftResult, *, demo_mode: bool) -> dict[str, str]:
    """Write MINUTA SUGERIDA artifacts (draft.md + optional contraponto)."""
    files: dict[str, str] = {}
    minuta_banner = banner_for(OutputMode.MINUTA_SUGERIDA)

    draft_path = out / draft_filename(OutputMode.MINUTA_SUGERIDA)
    draft_path.write_text(
        wrap_document(
            draft.draft_markdown,
            demo_mode=demo_mode,
            mode_banner=minuta_banner,
        ),
        encoding="utf-8",
    )
    files[draft_path.name] = _sha256(draft_path)

    if draft.contraponto_section:
        contra_path = out / "draft.contraponto.md"
        contra_path.write_text(
            wrap_document(
                draft.contraponto_section,
                demo_mode=demo_mode,
                mode_banner=minuta_banner,
            ),
            encoding="utf-8",
        )
        files[contra_path.name] = _sha256(contra_path)
    return files


def _write_rascunho(
    out: Path,
    draft: DraftResult,
    *,
    analysis: ProcessoAnalysis | None,
    demo_mode: bool,
) -> dict[str, str]:
    """Write the RASCUNHO DE PESQUISA research memo (no draft.md)."""
    body = build_rascunho_markdown(draft=draft, analysis=analysis)
    rascunho_path = out / draft_filename(OutputMode.RASCUNHO_PESQUISA)
    rascunho_path.write_text(
        wrap_document(
            body,
            demo_mode=demo_mode,
            mode_banner=banner_for(OutputMode.RASCUNHO_PESQUISA),
        ),
        encoding="utf-8",
    )
    return {rascunho_path.name: _sha256(rascunho_path)}


# ---------------------------------------------------------------------------
# Reviewer report
# ---------------------------------------------------------------------------


def _write_reviewer_report(out: Path, report: Any, *, demo_mode: bool) -> dict[str, str]:
    """Use ReviewReport.to_markdown() (already implemented) and wrap it."""
    body = report.to_markdown()
    path = out / "reviewer-report.md"
    path.write_text(wrap_document(body, demo_mode=demo_mode), encoding="utf-8")
    return {"reviewer-report.md": _sha256(path)}


# ---------------------------------------------------------------------------
# Prazos
# ---------------------------------------------------------------------------


def _write_prazos(out: Path, report: PrazoReport, *, demo_mode: bool) -> dict[str, str]:
    lines: list[str] = ["# Prazos", "", f"_{report.summary}_", ""]
    if not report.prazos:
        lines.append("Nenhum prazo pendente.")
    else:
        lines.append("| Status | Vencimento | Dias Úteis | Prazo | Base Legal | Ação |")
        lines.append("| --- | --- | ---: | --- | --- | --- |")
        for p in report.prazos:
            status = _status_label(p.status)
            lines.append(
                f"| {status} | {p.data_limite.strftime('%d/%m/%Y')} "
                f"| {p.dias_uteis_restantes} "
                f"| {p.rule.nome} "
                f"| {p.rule.base_legal} "
                f"| {p.rule.tipo_acao.value} |"
            )
    path = out / "prazos.md"
    path.write_text(wrap_document("\n".join(lines), demo_mode=demo_mode), encoding="utf-8")
    return {"prazos.md": _sha256(path)}


def _status_label(status: StatusPrazo) -> str:
    return {
        StatusPrazo.VENCIDO: "VENCIDO",
        StatusPrazo.URGENTE: "URGENTE",
        StatusPrazo.PROXIMO: "PRÓXIMO",
        StatusPrazo.ABERTO: "ABERTO",
        StatusPrazo.CUMPRIDO: "CUMPRIDO",
    }.get(status, "?")


# ---------------------------------------------------------------------------
# Case summary
# ---------------------------------------------------------------------------


def _write_case_summary(out: Path, result: DemoResult, *, demo_mode: bool) -> dict[str, str]:
    summary = serialize_processo_summary(result.processo)
    lines: list[str] = ["# Resumo do Caso", ""]
    lines.append(f"- **Número CNJ:** {summary['numero_cnj']}")
    lines.append(f"- **Tribunal:** {summary['tribunal']}")
    if summary["classe"]:
        lines.append(f"- **Classe:** {summary['classe']}")
    if summary["assunto"]:
        lines.append(f"- **Assunto:** {summary['assunto']}")
    if summary["valor_causa"] is not None:
        lines.append(f"- **Valor da causa:** R$ {summary['valor_causa']:,.2f}")
    if summary["orgao_julgador"]:
        lines.append(f"- **Órgão julgador:** {summary['orgao_julgador']}")
    if summary["data_ajuizamento"]:
        lines.append(f"- **Data de ajuizamento:** {summary['data_ajuizamento']}")
    lines.append(f"- **Movimentos:** {summary['movimentos_count']}")
    if summary["ultimo_movimento"]:
        um = summary["ultimo_movimento"]
        lines.append(f"- **Último movimento:** {um['data_hora']} — {um['descricao']}")

    if result.analysis is not None:
        lines.append("")
        lines.append("## Análise")
        lines.append("")
        lines.append(f"_{result.analysis.summary}_")
        if result.analysis.actionable:
            lines.append("")
            lines.append("**Ações pendentes:**")
            for a in result.analysis.actionable[:10]:
                lines.append(f"- [{a.urgencia.value}] {a.categoria.value}: {a.recomendacao}")

    if result.errors:
        lines.append("")
        lines.append("## Erros durante a execução")
        lines.append("")
        from juris.core.sanitize import safe_error_text

        for e in result.errors:
            lines.append(f"- {safe_error_text(e)}")

    path = out / "case-summary.md"
    path.write_text(wrap_document("\n".join(lines), demo_mode=demo_mode), encoding="utf-8")
    return {"case-summary.md": _sha256(path)}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _write_audit(out: Path, result: DemoResult) -> dict[str, str]:
    """Ensure audit.jsonl exists in the case folder + write the recap.

    The orchestrator is configured to write the audit log directly to
    `<out>/audit.jsonl` (see CLI `demo` command), so in the common path the
    source and destination are the same file. We still copy if they differ
    (e.g. when callers pass a custom audit_path for testing).
    """
    files: dict[str, str] = {}
    src = result.audit_log_path
    dst = out / "audit.jsonl"

    if src.exists() and src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    elif not dst.exists():
        # Empty log — keep an empty file so artifacts list stays consistent.
        dst.write_text("", encoding="utf-8")
    files["audit.jsonl"] = _sha256(dst)

    summary_path = out / "audit-summary.md"
    summary_path.write_text(_build_audit_summary(dst, result), encoding="utf-8")
    files["audit-summary.md"] = _sha256(summary_path)
    return files


def _build_audit_summary(audit_path: Path, result: DemoResult) -> str:
    log = AuditLog(audit_path)
    entries = log.read_all()
    corrupted = log.verify_integrity()

    lines: list[str] = ["# Audit — Resumo", ""]
    lines.append(f"- Arquivo: `{audit_path.name}`")
    lines.append(f"- Total de eventos: **{len(entries)}**")
    lines.append(f"- Integridade da cadeia: **{'OK' if not corrupted else f'{len(corrupted)} entradas corrompidas'}**")
    if entries:
        lines.append(f"- Primeiro evento: {entries[0].timestamp.isoformat()}")
        lines.append(f"- Último evento: {entries[-1].timestamp.isoformat()}")
        lines.append(f"- Hash final: `{entries[-1].content_hash}`")
    if corrupted:
        lines.append("")
        lines.append("## Entradas corrompidas")
        for cid in corrupted:
            lines.append(f"- {cid}")

    lines.append("")
    lines.append("## Eventos do demo")
    case_cnj = result.processo.numero_cnj
    case_events = [e for e in entries if e.processo_cnj == case_cnj]
    if not case_events:
        lines.append("_Nenhum evento atrelado a este processo._")
    else:
        for e in case_events:
            lines.append(f"- `{e.timestamp.isoformat()}` **{e.event_type}** _(actor: {e.actor})_")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------


def _build_manifest(result: DemoResult, artifacts: dict[str, str]) -> dict[str, Any]:
    draft = result.draft
    review = draft.reviewer_report if draft else None
    output_mode = result.request.output_mode
    return {
        "version": 1,
        "demo_mode": result.is_demo_mode,
        "output_mode": output_mode.value,
        "output_mode_label": label_for(output_mode),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "duration_seconds": result.duration_seconds,
        "succeeded": result.succeeded,
        "degraded": result.degraded,
        "degradation_reason": result.degradation_reason,
        "errors": result.errors,
        "request": {
            "numero_cnj": result.request.numero_cnj,
            "tipo_peticao": result.request.tipo_peticao.value,
            "tribunal": result.request.tribunal,
            "source": result.request.source.value,
            "use_cloud_llm": result.request.use_cloud_llm,
            "skip_review": result.request.skip_review,
            "thesis_explicit": result.request.thesis is not None,
            "output_mode": output_mode.value,
        },
        "llm_model": result.llm_model_used,
        "case_summary": serialize_processo_summary(result.processo),
        "analysis": (_analysis_payload(result.analysis) if result.analysis else None),
        "draft": (
            {
                "revisions": draft.revisions,
                "citations_count": len(draft.citations_used),
                "grounding_status": draft.grounding_report.status.value,
                "grounding_blocked_reason": draft.blocked_reason,
                "revisao_humana_obrigatoria": bool(
                    draft.estrategia and draft.estrategia.revisao_humana_obrigatoria
                ),
                "grounding_failed_citation_ids": draft.grounding_report.failed_citation_ids,
                "grounding_spurious_citations": draft.grounding_report.spurious_citations,
                "audit_entry_ids": draft.audit_entry_ids,
                "research_summary": draft.research_summary,
            }
            if draft
            else None
        ),
        "reviewer": (
            {
                "critical_count": review.critical_count,
                "important_count": review.important_count,
                "suggestion_count": review.suggestion_count,
            }
            if review
            else None
        ),
        "audit_log": "audit.jsonl",
        "out_dir": result.out_dir.name,
        "artifacts": [{"name": name, "sha256": digest} for name, digest in sorted(artifacts.items())],
    }


def _analysis_payload(analysis: ProcessoAnalysis) -> dict[str, Any]:
    return {
        "total_movimentos": analysis.total_movimentos,
        "rule_classified": analysis.rule_classified,
        "llm_calls": analysis.llm_calls,
        "actionable_count": len(analysis.actionable),
        "summary": analysis.summary,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


__all__ = ["write_artifacts"]
