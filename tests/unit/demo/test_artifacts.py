"""Tests for juris.demo.artifacts — artifact writing for demo runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from juris.agents.analyzer import AnalysisResult, ProcessoAnalysis
from juris.agents.citation_verifier import GroundingReport, GroundingStatus
from juris.agents.drafter import DraftResult
from juris.demo.artifacts import write_artifacts
from juris.demo.disclaimer import DEMO_BANNER, DISCLAIMER_FOOTER
from juris.demo.orchestrator import DemoRequest, DemoResult, SourceMode
from juris.demo.output_mode import (
    MINUTA_SUGERIDA_BANNER,
    RASCUNHO_PESQUISA_BANNER,
    OutputMode,
)
from juris.mni.parsers.processo import Movimento, Parte, ProcessoDomain
from juris.mni.tpu import CategoriaSemantica, Urgencia
from juris.persistence.audit import AuditLog
from juris.prazo.engine import Prazo, PrazoReport, StatusPrazo
from juris.prazo.rules import PrazoRule, TipoAcao
from juris.repertory.peticoes.models import TipoPeticao
from juris.review.models import (
    CitationRef,
    IssueSeverity,
    ReviewDimension,
    ReviewIssue,
    ReviewReport,
    ReviewRequest,
)


def _build_processo(cnj: str = "0001234-56.2026.8.13.0001") -> ProcessoDomain:
    now = datetime.now(UTC)
    return ProcessoDomain(
        numero_cnj=cnj,
        classe="Procedimento Comum Cível",
        assunto="Cobrança",
        valor_causa=10_000.00,
        tribunal="tjmg",
        movimentos=[
            Movimento(
                data_hora=now,
                tipo="movimentoNacional",
                codigo_nacional=12265,
                descricao="Citação realizada.",
                id_movimento="m1",
            ),
        ],
        partes=[
            Parte(nome="Autor", tipo="autor"),
            Parte(nome="Réu", tipo="reu"),
        ],
    )


def _build_request(
    cnj: str,
    *,
    source: SourceMode = SourceMode.FIXTURE,
    output_mode: OutputMode = OutputMode.MINUTA_SUGERIDA,
) -> DemoRequest:
    return DemoRequest(
        numero_cnj=cnj,
        tipo_peticao=TipoPeticao.CONTESTACAO,
        tribunal="tjmg",
        source=source,
        out_root=Path("juris-out"),
        output_mode=output_mode,
    )


def _build_analysis(cnj: str) -> ProcessoAnalysis:
    now = datetime.now(UTC)
    a = AnalysisResult(
        movimento_id="m1",
        codigo_tpu=12265,
        descricao="Citação",
        data_hora=now,
        categoria=CategoriaSemantica.CITACAO,
        urgencia=Urgencia.ALTA,
        requer_acao=True,
        recomendacao="Apresentar contestação.",
        confianca=0.95,
    )
    return ProcessoAnalysis(
        numero_cnj=cnj,
        tribunal="tjmg",
        total_movimentos=1,
        analyzed=[a],
        actionable=[a],
        rule_classified=1,
    )


def _build_prazo_report(cnj: str) -> PrazoReport:
    today = datetime.now(UTC).date()
    rule = PrazoRule(
        nome="Contestação",
        categoria_trigger=CategoriaSemantica.CITACAO,
        codigo_tpu=None,
        dias_uteis=15,
        tipo_acao=TipoAcao.CONTESTAR,
        base_legal="Art. 335 CPC",
    )
    prazo = Prazo(
        movimento_id="m1",
        numero_cnj=cnj,
        rule=rule,
        data_inicio=today,
        data_limite=today,
        dias_uteis_total=15,
        dias_uteis_restantes=10,
        status=StatusPrazo.ABERTO,
        categoria=CategoriaSemantica.CITACAO,
        urgencia=Urgencia.ALTA,
    )
    return PrazoReport(
        numero_cnj=cnj,
        tribunal="tjmg",
        computed_at=today,
        prazos=[prazo],
    )


def _build_review_report(cnj: str) -> ReviewReport:
    return ReviewReport(
        request=ReviewRequest(
            petition_text="texto",
            petition_type="contestacao",
            numero_cnj=cnj,
            tribunal="tjmg",
        ),
        issues=[
            ReviewIssue(
                dimension=ReviewDimension.STRUCTURE,
                severity=IssueSeverity.SUGGESTION,
                title="Sugestão A",
                description="Detalhe sugestão.",
            ),
        ],
        citations_found=[
            CitationRef(
                raw_text="Art. 335 CPC",
                normalized="art. 335 cpc",
                found_in_repertory=True,
            ),
        ],
        model_used="ollama:qwen3",
    )


def _build_draft(cnj: str, *, with_review: bool = True) -> DraftResult:
    return DraftResult(
        draft_markdown="# Petição\n\nCorpo.",
        contraponto_section="## Contraponto\nResposta.",
        citations_used=[],
        research_summary="resumo",
        reviewer_report=_build_review_report(cnj) if with_review else None,
        revisions=1,
        total_duration_seconds=1.2,
        audit_entry_ids=["e1", "e2"],
    )


def _build_result(
    tmp_path: Path,
    *,
    cnj: str = "0001234-56.2026.8.13.0001",
    is_demo_mode: bool = True,
    include_draft: bool = True,
    include_review: bool = True,
    include_prazos: bool = True,
    errors: list[str] | None = None,
    output_mode: OutputMode = OutputMode.MINUTA_SUGERIDA,
) -> DemoResult:
    out_dir = tmp_path / ("DEMO-" + cnj.replace("/", "_") if is_demo_mode else cnj)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = out_dir / "audit.jsonl"
    audit = AuditLog(audit_path)
    audit.log(
        event_type="demo.started",
        actor="system",
        details={"tipo_peticao": "contestacao", "demo_mode": is_demo_mode},
        processo_cnj=cnj,
    )
    audit.log(
        event_type="demo.finished",
        actor="system",
        details={"succeeded": include_draft and not errors},
        processo_cnj=cnj,
    )

    started = datetime.now(UTC)
    return DemoResult(
        request=_build_request(cnj, output_mode=output_mode),
        processo=_build_processo(cnj),
        out_dir=out_dir,
        is_demo_mode=is_demo_mode,
        started_at=started,
        finished_at=started,
        duration_seconds=2.0,
        audit_log_path=audit_path,
        analysis=_build_analysis(cnj),
        prazo_report=_build_prazo_report(cnj) if include_prazos else None,
        draft=_build_draft(cnj, with_review=include_review) if include_draft else None,
        errors=errors or [],
        llm_model_used="ollama:qwen3",
    )


class TestWriteArtifactsHappyPath:
    def test_writes_all_expected_files(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path)
        artifacts = write_artifacts(result)

        expected = {
            "draft.md",
            "draft.contraponto.md",
            "reviewer-report.md",
            "prazos.md",
            "case-summary.md",
            "audit.jsonl",
            "audit-summary.md",
            "run-manifest.json",
        }
        assert expected <= set(artifacts)
        for name in expected:
            assert (result.out_dir / name).exists()

    def test_returns_sha256_per_artifact(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path)
        artifacts = write_artifacts(result)
        for digest in artifacts.values():
            assert isinstance(digest, str)
            assert len(digest) == 64  # sha256 hex

    def test_run_manifest_contains_all_artifact_hashes(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path)
        artifacts = write_artifacts(result)
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())
        manifest_names = {a["name"] for a in manifest["artifacts"]}
        # run-manifest.json itself appears in the artifacts dict but its hash
        # is computed *after* it is written, so it is added to artifacts after
        # the manifest payload is built — it's not in the manifest list itself.
        assert (set(artifacts) - {"run-manifest.json"}) <= manifest_names
        assert manifest["request"]["numero_cnj"] == result.request.numero_cnj
        assert manifest["draft"]["grounding_status"] == "verified"
        assert manifest["draft"]["grounding_blocked_reason"] is None
        assert manifest["audit_log"] == "audit.jsonl"
        assert manifest["out_dir"] == result.out_dir.name
        assert str(tmp_path) not in json.dumps(manifest)

    def test_run_manifest_records_blocked_grounding(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path)
        assert result.draft is not None
        result.draft.grounding_report = GroundingReport(
            status=GroundingStatus.BLOCKED,
            failed_citation_ids=["inventado"],
            spurious_citations=["REsp 123456"],
            reason="citacoes_invalidas+citacoes_sem_marcador",
        )
        result.draft.blocked_reason = result.draft.grounding_report.reason

        write_artifacts(result)
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())

        assert manifest["draft"]["grounding_status"] == "blocked"
        assert manifest["draft"]["grounding_failed_citation_ids"] == ["inventado"]
        assert manifest["draft"]["grounding_spurious_citations"] == ["REsp 123456"]


class TestDemoModeGuards:
    def test_draft_in_demo_mode_has_banner_and_footer(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, is_demo_mode=True)
        write_artifacts(result)
        body = (result.out_dir / "draft.md").read_text()
        assert DEMO_BANNER in body
        assert DISCLAIMER_FOOTER in body
        # Banner appears before the petition content.
        assert body.index(DEMO_BANNER) < body.index("# Petição")

    def test_real_mode_draft_has_footer_but_no_banner(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, is_demo_mode=False)
        write_artifacts(result)
        body = (result.out_dir / "draft.md").read_text()
        assert DISCLAIMER_FOOTER in body
        assert DEMO_BANNER not in body

    def test_demo_banner_applied_to_every_lawyer_facing_doc(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, is_demo_mode=True)
        write_artifacts(result)
        for name in (
            "draft.md",
            "draft.contraponto.md",
            "reviewer-report.md",
            "prazos.md",
            "case-summary.md",
        ):
            body = (result.out_dir / name).read_text()
            assert DEMO_BANNER in body, f"banner missing from {name}"
            assert DISCLAIMER_FOOTER in body, f"footer missing from {name}"

    def test_run_manifest_records_demo_mode_flag(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, is_demo_mode=True)
        write_artifacts(result)
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())
        assert manifest["demo_mode"] is True


class TestPartialResults:
    def test_no_draft_skips_draft_artifacts_but_writes_summary(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, include_draft=False, errors=["draft: boom"])
        artifacts = write_artifacts(result)
        assert "draft.md" not in artifacts
        assert "reviewer-report.md" not in artifacts
        # case-summary, audit, manifest still produced.
        for required in ("case-summary.md", "audit.jsonl", "run-manifest.json"):
            assert required in artifacts
        # Errors are surfaced in case summary.
        body = (result.out_dir / "case-summary.md").read_text()
        assert "draft: boom" in body
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())
        assert manifest["succeeded"] is False
        assert manifest["errors"] == ["draft: boom"]

    def test_no_prazos_skips_prazos_file(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, include_prazos=False)
        artifacts = write_artifacts(result)
        assert "prazos.md" not in artifacts

    def test_no_reviewer_skips_reviewer_report(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, include_review=False)
        artifacts = write_artifacts(result)
        assert "reviewer-report.md" not in artifacts


class TestOutputModeArtifacts:
    """Sprint 17: artifact differences between MINUTA and RASCUNHO modes."""

    def test_minuta_mode_writes_draft_md(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, output_mode=OutputMode.MINUTA_SUGERIDA)
        artifacts = write_artifacts(result)
        assert "draft.md" in artifacts
        assert "rascunho-pesquisa.md" not in artifacts

    def test_rascunho_mode_writes_memo_not_draft(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, output_mode=OutputMode.RASCUNHO_PESQUISA)
        artifacts = write_artifacts(result)
        # Codex constraint: RASCUNHO must NEVER produce draft.md, so the
        # filesystem cannot suggest a fileable petition exists.
        assert "rascunho-pesquisa.md" in artifacts
        assert "draft.md" not in artifacts
        assert "draft.contraponto.md" not in artifacts

    def test_minuta_mode_banner_in_draft(self, tmp_path: Path) -> None:
        result = _build_result(
            tmp_path,
            is_demo_mode=False,
            output_mode=OutputMode.MINUTA_SUGERIDA,
        )
        write_artifacts(result)
        body = (result.out_dir / "draft.md").read_text()
        assert MINUTA_SUGERIDA_BANNER in body
        assert RASCUNHO_PESQUISA_BANNER not in body
        assert DISCLAIMER_FOOTER in body

    def test_rascunho_mode_banner_in_memo(self, tmp_path: Path) -> None:
        result = _build_result(
            tmp_path,
            is_demo_mode=False,
            output_mode=OutputMode.RASCUNHO_PESQUISA,
        )
        write_artifacts(result)
        body = (result.out_dir / "rascunho-pesquisa.md").read_text()
        assert RASCUNHO_PESQUISA_BANNER in body
        assert MINUTA_SUGERIDA_BANNER not in body
        assert DISCLAIMER_FOOTER in body

    def test_demo_mode_stacks_demo_and_mode_banners(self, tmp_path: Path) -> None:
        result = _build_result(
            tmp_path,
            is_demo_mode=True,
            output_mode=OutputMode.RASCUNHO_PESQUISA,
        )
        write_artifacts(result)
        body = (result.out_dir / "rascunho-pesquisa.md").read_text()
        # Both banners present; DEMO banner first, then mode banner.
        assert DEMO_BANNER in body
        assert RASCUNHO_PESQUISA_BANNER in body
        assert body.index(DEMO_BANNER) < body.index(RASCUNHO_PESQUISA_BANNER)

    def test_manifest_records_minuta_mode(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, output_mode=OutputMode.MINUTA_SUGERIDA)
        write_artifacts(result)
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())
        assert manifest["output_mode"] == "minuta-sugerida"
        assert manifest["output_mode_label"] == "MINUTA SUGERIDA"
        assert manifest["request"]["output_mode"] == "minuta-sugerida"

    def test_manifest_records_rascunho_mode(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, output_mode=OutputMode.RASCUNHO_PESQUISA)
        write_artifacts(result)
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())
        assert manifest["output_mode"] == "rascunho-pesquisa"
        assert manifest["output_mode_label"] == "RASCUNHO DE PESQUISA"
        # Manifest's artifact list reflects the mode-specific filename.
        names = {a["name"] for a in manifest["artifacts"]}
        assert "rascunho-pesquisa.md" in names
        assert "draft.md" not in names

    def test_manifest_records_degraded_run(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path, output_mode=OutputMode.RASCUNHO_PESQUISA)
        result.degraded = True
        result.degradation_reason = "All connection attempts failed"
        write_artifacts(result)
        manifest = json.loads((result.out_dir / "run-manifest.json").read_text())
        assert manifest["degraded"] is True
        assert manifest["degradation_reason"] == "All connection attempts failed"


class TestAuditCopying:
    def test_audit_jsonl_is_present_in_out_dir(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path)
        write_artifacts(result)
        audit_file = result.out_dir / "audit.jsonl"
        assert audit_file.exists()
        # File has entries from the helper.
        assert audit_file.read_text().strip()

    def test_audit_summary_lists_demo_events(self, tmp_path: Path) -> None:
        result = _build_result(tmp_path)
        write_artifacts(result)
        body = (result.out_dir / "audit-summary.md").read_text()
        assert "demo.started" in body
        assert "demo.finished" in body
        assert "OK" in body  # chain integrity

    def test_audit_summary_when_log_empty(self, tmp_path: Path) -> None:
        cnj = "0009999-00.2026.8.13.0001"
        out_dir = tmp_path / ("DEMO-" + cnj)
        out_dir.mkdir(parents=True)
        audit_path = out_dir / "audit.jsonl"
        audit_path.write_text("")
        started = datetime.now(UTC)
        result = DemoResult(
            request=_build_request(cnj),
            processo=_build_processo(cnj),
            out_dir=out_dir,
            is_demo_mode=True,
            started_at=started,
            finished_at=started,
            duration_seconds=0.1,
            audit_log_path=audit_path,
        )
        write_artifacts(result)
        body = (result.out_dir / "audit-summary.md").read_text()
        assert "Total de eventos: **0**" in body
