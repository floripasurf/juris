"""De-identification — the first-class capability behind ADR-0016's cloud path.

To offer "AI of preference" (cloud LLMs) without leaking PII (LGPD / OAB sigilo),
case content is pseudonymized before it leaves the perimeter: direct identifiers
become reversible placeholders, and a re-identification map is kept locally so
the model's output can be restored.

This baseline handles **structured** identifiers (CPF, CNPJ, CNJ, OAB, RG, CEP,
e-mail, phone, monetary values, full dates) — the highest-risk, reliably
regex-detectable ones. Free-text identifiers (party names, street addresses) are
where a NER model adds value: pass a ``ner_redactor`` callable (e.g. backed by
LeNER-Br) to extend coverage. Imperfect de-id is flagged, never assumed complete
— the default posture stays "never send raw PII to cloud".
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Order matters and is load-bearing: the most specific / longest identifiers run
# first so a later, looser pattern can't carve a fragment out of one already
# matched. CNJ (dotted) → CNPJ → CPF → RG → OAB → monetary (R$-anchored) → CEP →
# phone → date → email. Every match becomes a reversible placeholder, so redacting
# values/dates costs no draft fidelity (reidentify restores them).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CNJ", re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")),
    ("CNPJ", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    ("CPF", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    # RG: 2.3.3-1 (check digit may be X). Distinct from CPF's 3.3.3-2 shape.
    ("RG", re.compile(r"\b\d{2}\.\d{3}\.\d{3}-[\dxX]\b")),
    # OAB number: optional "nº" lead-in, dotted thousands (234.567) OR plain (123456).
    # The old \d{1,6} stopped at the dot and leaked the ".567" tail.
    (
        "OAB",
        re.compile(
            r"\bOAB[/\s]?[A-Z]{2}\s*(?:n[º°.]?\s*)?(?:\d{1,3}(?:\.\d{3})+|\d{1,6})\b", re.IGNORECASE
        ),
    ),
    # Monetary value — anchored on R$ so it never collides with a bare id number.
    ("VALOR", re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?")),
    # CEP: 5-3 digits (phone is dash-then-4, so no overlap).
    ("CEP", re.compile(r"\b\d{5}-\d{3}\b")),
    # Brazilian phone: optional +55, optional (DD)/DD, then 4-4 or 5-4 (mobile).
    ("TELEFONE", re.compile(r"(?<!\d)(?:\+55\s?)?(?:\(\d{2}\)\s?|\d{2}\s)?\d{4,5}-\d{4}(?!\d)")),
    # Full date dd/mm/yyyy (weakly identifying, e.g. birth dates); reversible.
    ("DATA", re.compile(r"\b\d{2}/\d{2}/\d{4}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
]


@dataclass(frozen=True, slots=True)
class DeidResult:
    """De-identified text plus the local re-identification map."""

    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder → original
    complete: bool = False
    """True only when free-text entities were also handled (a ``ner_redactor``
    ran). Structured-only de-id leaves names/addresses in place — partial, and
    not cloud-safe by default."""


def deidentify(text: str, *, ner_redactor: Callable[[str], list[str]] | None = None) -> DeidResult:
    """Replace direct identifiers with reversible placeholders.

    Args:
        text: Raw case text.
        ner_redactor: Optional callable returning entity spans to redact (e.g.
            names/orgs from a LeNER-Br model). Each returned string is replaced.

    Returns:
        :class:`DeidResult` with the de-identified text and the re-id map.
    """
    mapping: dict[str, str] = {}
    reverse: dict[str, str] = {}  # original → placeholder (stable)
    counters: dict[str, int] = {}

    def _placeholder(label: str, original: str) -> str:
        if original in reverse:
            return reverse[original]
        counters[label] = counters.get(label, 0) + 1
        ph = f"[{label}_{counters[label]}]"
        mapping[ph] = original
        reverse[original] = ph
        return ph

    def _repl_for(label: str) -> Callable[[re.Match[str]], str]:
        def repl(match: re.Match[str]) -> str:
            return _placeholder(label, match.group(0))

        return repl

    out = text
    for label, pattern in _PATTERNS:
        out = pattern.sub(_repl_for(label), out)

    if ner_redactor is not None:
        for entity in ner_redactor(text):
            if entity and entity in out:
                out = out.replace(entity, _placeholder("NOME", entity))

    # "Complete" only when free-text entities were processed; structured-only
    # de-id leaves names in place and must not be assumed cloud-safe.
    return DeidResult(text=out, mapping=mapping, complete=ner_redactor is not None)


def ensure_cloud_safe(result: DeidResult, *, allow_partial: bool = False) -> None:
    """Gate before sending de-identified text to a cloud LLM (ADR-0016).

    Raises:
        ValueError: if the de-identification is partial (structured-only, names
            may remain) and the caller did not explicitly opt in via
            ``allow_partial`` (which requires a documented consent/DPA path).
    """
    if not result.complete and not allow_partial:
        msg = (
            "De-identificação parcial (apenas identificadores estruturados; "
            "nomes podem permanecer). Forneça um ner_redactor (LeNER-Br) ou "
            "use allow_partial=True com consentimento/DPA explícito."
        )
        raise ValueError(msg)


def reidentify(text: str, mapping: dict[str, str]) -> str:
    """Restore the original identifiers from a de-identification map."""
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text
