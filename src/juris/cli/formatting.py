"""Presentation helpers for the CLI (kept pure + tracked for CI coverage)."""

from __future__ import annotations

# Short labels for the composite-score components (ADR-0017 auditability).
_COMPONENT_LABELS: dict[str, str] = {
    "relevancia": "rel",
    "autoridade": "aut",
    "vigencia": "vig",
    "corroboracao": "cor",
    "recencia": "rec",
    "pacificacao": "pac",
}


def format_score_components(
    components: dict[str, float] | None, *, max_parts: int = 4
) -> str:
    """Render a composite-score breakdown as a compact, auditable one-liner.

    Shows the signals that actually contributed, highest first (e.g.
    ``"rel 0.28 · aut 0.20 · vig 0.15"``), so the lawyer sees *why* a precedent
    ranked. Zero contributions and the ``total`` are omitted.

    Args:
        components: The ``score_components`` mapping from a RetrievalResult, or
            None when the composite ranker wasn't active.
        max_parts: Cap on the number of components shown.

    Returns:
        A formatted string, or "" when there's nothing to show.
    """
    if not components:
        return ""
    parts = [
        (label, components[key])
        for key, label in _COMPONENT_LABELS.items()
        if components.get(key, 0.0) > 0.0
    ]
    parts.sort(key=lambda part: part[1], reverse=True)
    return " · ".join(f"{label} {value:.2f}" for label, value in parts[:max_parts])
