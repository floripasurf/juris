"""Tests for juris.demo.rascunho — RASCUNHO DE PESQUISA memo builder."""

from __future__ import annotations

from datetime import UTC, datetime

from juris.agents.analyzer import AnalysisResult, ProcessoAnalysis
from juris.agents.citation_verifier import CitationCheck, GroundingReport, GroundingStatus
from juris.agents.drafter import DraftResult
from juris.demo.rascunho import build_rascunho_markdown
from juris.mni.tpu import CategoriaSemantica, Urgencia


def _draft(
    *,
    body: str = "# Petição\n\n## Dos fatos\nA.\n\n## Do direito\nB.",
    contraponto: str = "Resposta esperada da parte adversa.",
    citations: list[CitationCheck] | None = None,
    research: str = "Pesquisa: 3 acórdãos relevantes encontrados.",
) -> DraftResult:
    return DraftResult(
        draft_markdown=body,
        contraponto_section=contraponto,
        citations_used=citations or [],
        research_summary=research,
    )


def _cite(
    source_id: str = "stf-sumula-7",
    *,
    resolved: bool = True,
    excerpt: str | None = "Trecho ilustrativo da súmula.",
) -> CitationCheck:
    return CitationCheck(
        raw_marker=f"[CITE:{source_id}]",
        source_id=source_id,
        resolved=resolved,
        available_excerpt=excerpt,
        span_in_draft=(0, len(source_id)),
    )


def _analysis() -> ProcessoAnalysis:
    """Build a ProcessoAnalysis whose computed ``summary`` property reports
    one actionable item — used to verify the memo includes the analyzer's
    summary line and the action's recommendation.
    """
    a = AnalysisResult(
        movimento_id="m1",
        codigo_tpu=12265,
        descricao="Citação",
        data_hora=datetime.now(UTC),
        categoria=CategoriaSemantica.CITACAO,
        urgencia=Urgencia.ALTA,
        requer_acao=True,
        recomendacao="Apresentar contestação no prazo.",
        confianca=0.95,
    )
    return ProcessoAnalysis(
        numero_cnj="0001234-56.2026.8.13.0001",
        tribunal="tjmg",
        total_movimentos=1,
        analyzed=[a],
        actionable=[a],
        rule_classified=1,
    )


class TestRascunhoStructure:
    def test_includes_all_required_sections(self) -> None:
        body = build_rascunho_markdown(draft=_draft(), analysis=_analysis())
        for section in (
            "# Memorando de Pesquisa Jurídica",
            "## Análise jurídica",
            "## Argumentos sugeridos",
            "## Riscos / contraponto",
            "## Esqueleto sugerido para a peça",
            "## Próximos passos",
        ):
            assert section in body, f"section missing: {section}"

    def test_no_petition_prose_in_memo(self) -> None:
        # The memo must NOT include the drafter's petition prose verbatim —
        # it offers structure + research, never a body. This is the safety
        # contract that justifies the separate filename.
        prose = "Excelentíssimo Senhor Doutor Juiz prose."
        draft = _draft(body=f"# Petição\n\n{prose}\n\n## Dos fatos\nA.")
        body = build_rascunho_markdown(draft=draft, analysis=None)
        assert prose not in body


class TestAnaliseJuridicaSection:
    def test_includes_research_summary(self) -> None:
        body = build_rascunho_markdown(
            draft=_draft(research="Pesquisa: STF Súmula 7."),
            analysis=None,
        )
        assert "Pesquisa: STF Súmula 7." in body

    def test_includes_analysis_summary_and_actions(self) -> None:
        body = build_rascunho_markdown(draft=_draft(research=""), analysis=_analysis())
        # ``ProcessoAnalysis.summary`` is computed; assert against the
        # actually-produced text rather than a fictional override.
        assert "0001234-56.2026.8.13.0001" in body
        assert "ações pendentes" in body
        assert "Apresentar contestação no prazo." in body
        assert "Ações pendentes identificadas" in body

    def test_graceful_when_research_and_analysis_missing(self) -> None:
        body = build_rascunho_markdown(draft=_draft(research=""), analysis=None)
        assert "Sem dados de pesquisa disponíveis" in body

    def test_surfaces_blocked_grounding_status(self) -> None:
        draft = _draft(research="")
        draft.grounding_report = GroundingReport(
            status=GroundingStatus.BLOCKED,
            failed_citation_ids=["inventado"],
            spurious_citations=["REsp 123456"],
            reason="citacoes_invalidas+citacoes_sem_marcador",
        )
        draft.blocked_reason = draft.grounding_report.reason

        body = build_rascunho_markdown(draft=draft, analysis=None)

        assert "Status de verificação:** BLOQUEADO" in body
        assert "`inventado`" in body
        assert "REsp 123456" in body


class TestArgumentosSugeridosSection:
    def test_lists_only_resolved_citations(self) -> None:
        cites = [
            _cite("stf-sumula-7", resolved=True),
            _cite("invalid-marker", resolved=False),
        ]
        body = build_rascunho_markdown(draft=_draft(citations=cites), analysis=None)
        assert "[CITE:stf-sumula-7]" in body
        assert "[CITE:invalid-marker]" not in body

    def test_renders_excerpt_when_available(self) -> None:
        cites = [_cite("art-335-cpc", excerpt="Texto do art. 335 CPC.")]
        body = build_rascunho_markdown(draft=_draft(citations=cites), analysis=None)
        assert "Texto do art. 335 CPC." in body

    def test_handles_excerpt_absent(self) -> None:
        cites = [_cite("art-335-cpc", excerpt=None)]
        body = build_rascunho_markdown(draft=_draft(citations=cites), analysis=None)
        # No "—" separator when excerpt is empty.
        assert "[CITE:art-335-cpc]" in body
        assert "[CITE:art-335-cpc] —" not in body

    def test_empty_citations_message(self) -> None:
        body = build_rascunho_markdown(draft=_draft(citations=[]), analysis=None)
        assert "Nenhuma citação verificada" in body


class TestRiscosSection:
    def test_uses_drafter_contraponto(self) -> None:
        body = build_rascunho_markdown(
            draft=_draft(contraponto="A parte contrária argumentará X."),
            analysis=None,
        )
        assert "A parte contrária argumentará X." in body

    def test_empty_contraponto_message(self) -> None:
        body = build_rascunho_markdown(draft=_draft(contraponto=""), analysis=None)
        assert "Nenhum contraponto formulado" in body


class TestEsqueletoSection:
    def test_extracts_h2_h3_headings(self) -> None:
        body = build_rascunho_markdown(
            draft=_draft(body=("# Petição\n\n## Endereçamento\nblah\n## Qualificação\nblah\n### Subseção\nblah\n")),
            analysis=None,
        )
        assert "- Endereçamento" in body
        assert "- Qualificação" in body
        assert "- Subseção" in body

    def test_dedupes_repeated_headings(self) -> None:
        body = build_rascunho_markdown(
            draft=_draft(body=("## Dos fatos\nx\n## Do direito\ny\n## Dos fatos\nz\n")),
            analysis=None,
        )
        # "Dos fatos" should appear only once in the skeleton list.
        assert body.count("- Dos fatos") == 1

    def test_falls_back_to_default_skeleton(self) -> None:
        body = build_rascunho_markdown(
            draft=_draft(body="Just some prose with no headings."),
            analysis=None,
        )
        # Generic fallback skeleton.
        assert "- Endereçamento" in body
        assert "- Qualificação das partes" in body
        assert "- Dos pedidos" in body

    def test_skeleton_includes_lawyer_redaction_note(self) -> None:
        body = build_rascunho_markdown(draft=_draft(), analysis=None)
        assert "redigido pelo(a) advogado(a)" in body


class TestProximosPassos:
    def test_includes_validation_steps(self) -> None:
        body = build_rascunho_markdown(draft=_draft(), analysis=None)
        assert "## Próximos passos" in body
        assert "Validar a aplicabilidade" in body
        assert "Submeter a peça redigida à revisão" in body
