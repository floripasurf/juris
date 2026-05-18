"""Build the RASCUNHO DE PESQUISA artifact from existing drafter output.

When the operator selects ``--modo rascunho-pesquisa``, a normal demo run still
exercises the full pipeline (analyze → prazos → draft → reviewer), but the
primary artifact is a **research memo** rather than a petition draft. If the
local Ollama call is unavailable, the orchestrator may supply a deterministic
``DraftResult`` skeleton instead; that degraded run is marked on
``DemoResult.degraded`` and in ``run-manifest.json``.

The memo is composed deterministically from existing ``DraftResult`` fields
plus the run's :class:`ProcessoAnalysis`. **No additional LLM calls are
made here** — the transformation is structural, not generative. This keeps
the mode honest: we present what the pipeline already gathered, organised
for a lawyer who will draft the actual petition by hand.

Sections:

* **Análise jurídica** — research summary + processo analysis
* **Argumentos sugeridos** — numbered list derived from verified citations
* **Riscos / contraponto** — uses the drafter's contraponto section
* **Esqueleto sugerido** — H2/H3 headings extracted from the draft markdown
* **Próximos passos** — fixed checklist for the lawyer

The artifacts module is responsible for prepending the
:data:`juris.demo.output_mode.RASCUNHO_PESQUISA_BANNER` and appending the
universal disclaimer footer.
"""

from __future__ import annotations

import re

from juris.agents.analyzer import ProcessoAnalysis
from juris.agents.drafter import DraftResult

# Fallback skeleton when the draft contains no extractable headings. Generic
# enough to be safe across petition types; the lawyer is expected to adapt.
_FALLBACK_SECTIONS: tuple[str, ...] = (
    "Endereçamento",
    "Qualificação das partes",
    "Dos fatos",
    "Do direito",
    "Dos pedidos",
)

_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")


def build_rascunho_markdown(
    *,
    draft: DraftResult,
    analysis: ProcessoAnalysis | None,
) -> str:
    """Compose the research memo body for a ``RASCUNHO DE PESQUISA`` run.

    Args:
        draft: Drafter output produced by the same pipeline that would have
            produced a MINUTA. Used as raw material — its prose is *not*
            included verbatim.
        analysis: Processo analysis from the demo run. Optional; when
            absent the analysis section degrades gracefully.

    Returns:
        Markdown body suitable for wrapping with the universal disclaimer
        footer. Does **not** include the RASCUNHO banner — the caller adds
        it via ``wrap_document(..., mode_banner=...)``.
    """
    parts: list[str] = ["# Memorando de Pesquisa Jurídica", ""]
    parts.append(_render_analise_juridica(draft, analysis))
    parts.append(_render_argumentos_sugeridos(draft))
    parts.append(_render_riscos(draft))
    parts.append(_render_esqueleto(draft))
    parts.append(_render_proximos_passos())
    return "\n".join(p for p in parts if p is not None)


def _render_analise_juridica(draft: DraftResult, analysis: ProcessoAnalysis | None) -> str:
    out: list[str] = ["## Análise jurídica", ""]
    if draft.research_summary.strip():
        out.append(draft.research_summary.strip())
        out.append("")
    if analysis is not None:
        if analysis.summary:
            out.append(f"_{analysis.summary}_")
            out.append("")
        if analysis.actionable:
            out.append("**Ações pendentes identificadas:**")
            out.append("")
            for a in analysis.actionable[:10]:
                out.append(f"- [{a.urgencia.value}] {a.categoria.value}: {a.recomendacao}")
            out.append("")
    if not draft.research_summary.strip() and analysis is None:
        out.append("_Sem dados de pesquisa disponíveis nesta execução._")
        out.append("")
    return "\n".join(out)


def _render_argumentos_sugeridos(draft: DraftResult) -> str:
    """List verified citations as a numbered argument scaffold.

    Uses :class:`CitationCheck` fields directly: ``source_id`` is the
    canonical identifier (e.g. ``stf-sumula-7``), ``resolved`` flags whether
    the marker was found in the corpus, and ``available_excerpt`` is the
    snippet (when present).
    """
    out: list[str] = ["## Argumentos sugeridos", ""]
    cites = [c for c in draft.citations_used if c.resolved]
    if not cites:
        out.append("_Nenhuma citação verificada disponível para sustentar argumentos._")
        out.append("")
        return "\n".join(out)
    for i, c in enumerate(cites, start=1):
        excerpt = (c.available_excerpt or "").strip()
        line = f"{i}. `[CITE:{c.source_id}]`"
        if excerpt:
            line += f" — {excerpt}"
        out.append(line)
    out.append("")
    return "\n".join(out)


def _render_riscos(draft: DraftResult) -> str:
    out: list[str] = ["## Riscos / contraponto", ""]
    body = draft.contraponto_section.strip()
    if body:
        out.append(body)
    else:
        out.append("_Nenhum contraponto formulado nesta execução._")
    out.append("")
    return "\n".join(out)


def _render_esqueleto(draft: DraftResult) -> str:
    out: list[str] = ["## Esqueleto sugerido para a peça", ""]
    headings = _extract_section_headings(draft.draft_markdown)
    if not headings:
        headings = list(_FALLBACK_SECTIONS)
    for h in headings:
        out.append(f"- {h}")
    out.append("")
    out.append("_Os tópicos acima refletem a estrutura sugerida; o conteúdo deve ser redigido pelo(a) advogado(a)._")
    out.append("")
    return "\n".join(out)


def _render_proximos_passos() -> str:
    return (
        "## Próximos passos\n"
        "\n"
        "1. Validar a aplicabilidade dos argumentos ao caso concreto.\n"
        "2. Conferir a vigência e o entendimento atual das fontes citadas.\n"
        "3. Redigir a peça utilizando o esqueleto como guia.\n"
        "4. Submeter a peça redigida à revisão antes do protocolo.\n"
    )


def _extract_section_headings(markdown: str) -> list[str]:
    """Extract H2/H3 headings from a markdown body, in order, deduped.

    Used to give the operator a quick view of the structure the drafter
    would have produced — without the body prose, which is the whole point
    of RASCUNHO mode.
    """
    headings: list[str] = []
    seen: set[str] = set()
    for line in markdown.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            title = m.group(1).strip()
            if title and title not in seen:
                seen.add(title)
                headings.append(title)
    return headings


__all__ = ["build_rascunho_markdown"]
