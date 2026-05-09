"""Disclaimer text and DEMO MODE guards for lawyer-facing artifacts.

Single source of truth for any lawyer-visible safety text. Every generated
document in the demo pipeline must pass through one of the helpers here so
fixture output cannot be mistaken for a real petition.
"""

from __future__ import annotations

from juris.core.observability import get_logger

logger = get_logger(__name__)


# Universal AI-disclosure footer printed on every generated document.
DISCLAIMER_FOOTER: str = (
    "---\n\n"
    "_Saída gerada por inteligência artificial. "
    "Revisão por advogado(a) inscrito(a) na OAB obrigatória antes de uso processual. "
    "A IA assiste o(a) advogado(a); a responsabilidade pelo conteúdo permanece "
    "exclusivamente com o(a) profissional inscrito(a) na OAB._"
)

# Banner placed at the very top of every fixture-mode artifact. Loud, repeated,
# in PT-BR so a lawyer cannot miss it.
DEMO_BANNER: str = (
    "> ⚠️ **MODO DEMONSTRAÇÃO — NÃO PROTOCOLAR** ⚠️\n"
    ">\n"
    "> Este documento foi gerado em **modo de demonstração** com dados de\n"
    "> fixture. **Não corresponde a um processo real e não pode ser\n"
    "> protocolado, assinado ou utilizado processualmente sob nenhuma\n"
    "> hipótese.**\n"
)

# Filename prefix for fixture-mode output directories.
DEMO_DIR_PREFIX: str = "DEMO-"

# Substring used to flag fixture-mode artifacts in run-manifest.json.
DEMO_MODE_FLAG: str = "demo_mode_fixture"


def wrap_document(
    body: str,
    *,
    demo_mode: bool,
    mode_banner: str | None = None,
) -> str:
    """Apply DEMO banner, mode banner, and disclaimer footer to a document.

    Args:
        body: The document body (typically markdown).
        demo_mode: If True, prepend :data:`DEMO_BANNER` (loud, fixture-only).
        mode_banner: Optional mode-specific banner (e.g.
            ``MINUTA_SUGERIDA_BANNER`` or ``RASCUNHO_PESQUISA_BANNER``)
            inserted between the DEMO banner and the body. Sprint 17.

    Returns:
        The body with both banners (where applicable) and
        :data:`DISCLAIMER_FOOTER` applied.
    """
    parts: list[str] = []
    if demo_mode:
        parts.append(DEMO_BANNER)
        parts.append("")  # blank line after DEMO banner
    if mode_banner:
        parts.append(mode_banner)
        parts.append("")  # blank line after mode banner
    parts.append(body.rstrip())
    parts.append("")  # blank line before footer
    parts.append(DISCLAIMER_FOOTER)
    return "\n".join(parts) + "\n"


def output_dir_name(numero_cnj: str, *, demo_mode: bool) -> str:
    """Compute the output directory name for a demo run.

    Fixture-mode runs are forced under a `DEMO-` prefix so artifacts can never
    be confused with real cases at the filesystem level.
    """
    safe_cnj = numero_cnj.replace("/", "_").replace(" ", "_")
    if demo_mode:
        return f"{DEMO_DIR_PREFIX}{safe_cnj}"
    return safe_cnj
