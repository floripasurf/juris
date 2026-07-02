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
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class _PatternSpec:
    label: str
    pattern: re.Pattern[str]
    validator: Callable[[str], bool] | None = None


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _valid_cpf_digits(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * len(digits):
        return False
    for pos in (9, 10):
        total = sum(int(digits[index]) * (pos + 1 - index) for index in range(pos))
        check = (total * 10) % 11
        if check == 10:
            check = 0
        if check != int(digits[pos]):
            return False
    return True


def _valid_cnpj_digits(digits: str) -> bool:
    if len(digits) != 14 or digits == digits[0] * len(digits):
        return False
    weights_first = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_second = [6, *weights_first]
    for size, weights in ((12, weights_first), (13, weights_second)):
        total = sum(int(digits[index]) * weights[index] for index in range(size))
        remainder = total % 11
        check = 0 if remainder < 2 else 11 - remainder
        if check != int(digits[size]):
            return False
    return True


def _valid_cnj_digits(digits: str) -> bool:
    if len(digits) != 20 or digits == digits[0] * len(digits):
        return False
    # CNJ Mod 97: NNNNNNNYYYYJTRTR0000DD must leave remainder 1.
    sequence = digits[:7]
    check_digits = digits[7:9]
    year_and_court = digits[9:]
    return int(f"{sequence}{year_and_court}{check_digits}") % 97 == 1


def _valid_cpf(value: str) -> bool:
    return _valid_cpf_digits(_digits_only(value))


def _valid_cnpj(value: str) -> bool:
    return _valid_cnpj_digits(_digits_only(value))


def _valid_cnj(value: str) -> bool:
    return _valid_cnj_digits(_digits_only(value))


# Order matters and is load-bearing: the most specific / longest identifiers run
# first so a later, looser pattern can't carve a fragment out of one already
# matched. CNJ (formatted/raw) → CNPJ (formatted/raw) → CPF (formatted/raw) → RG
# → OAB → monetary (R$-anchored) → CEP → phone → date → email. Raw digit-only
# CPF/CNPJ/CNJ patterns are checksum-gated to avoid redacting ordinary numbers.
_PATTERNS: list[_PatternSpec] = [
    _PatternSpec("CNJ", re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")),
    _PatternSpec("CNJ", re.compile(r"\b\d{20}\b"), _valid_cnj),
    _PatternSpec("CNPJ", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    _PatternSpec("CNPJ", re.compile(r"\b\d{14}\b"), _valid_cnpj),
    _PatternSpec("CPF", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    _PatternSpec("CPF", re.compile(r"\b\d{11}\b"), _valid_cpf),
    # RG: 2.3.3-1 (check digit may be X). Distinct from CPF's 3.3.3-2 shape.
    _PatternSpec("RG", re.compile(r"\b\d{2}\.\d{3}\.\d{3}-[\dxX]\b")),
    # OAB number: optional "nº" lead-in, dotted thousands (234.567) OR plain (123456).
    # The old \d{1,6} stopped at the dot and leaked the ".567" tail.
    _PatternSpec(
        "OAB",
        re.compile(
            r"\bOAB[/\s]?[A-Z]{2}\s*(?:n[º°.]?\s*)?(?:\d{1,3}(?:\.\d{3})+|\d{1,6})\b", re.IGNORECASE
        ),
    ),
    # Monetary value — anchored on R$ so it never collides with a bare id number.
    _PatternSpec("VALOR", re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?")),
    # CEP: 5-3 digits (phone is dash-then-4, so no overlap).
    _PatternSpec("CEP", re.compile(r"\b\d{5}-\d{3}\b")),
    # Brazilian phone: optional +55, optional (DD)/DD, then 4-4 or 5-4 (mobile).
    _PatternSpec("TELEFONE", re.compile(r"(?<!\d)(?:\+55\s?)?(?:\(\d{2}\)\s?|\d{2}\s)?\d{4,5}-\d{4}(?!\d)")),
    # Full date dd/mm/yyyy (weakly identifying, e.g. birth dates); reversible.
    _PatternSpec("DATA", re.compile(r"\b\d{2}/\d{2}/\d{4}\b")),
    _PatternSpec("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
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


class Deidentifier:
    """Stateful de-identifier sharing ONE placeholder map across many texts.

    A single instance keeps a stable mapping, so the same identifier (a party name
    repeated across every movement, a CPF in two fields) always maps to the same
    placeholder. This is what lets a structured record — e.g. a whole processo — be
    de-identified field-by-field yet stay consistently reversible from one map.
    """

    def __init__(self, *, ner_redactor: Callable[[str], list[str]] | None = None) -> None:
        self._mapping: dict[str, str] = {}
        self._reverse: dict[str, str] = {}  # original → placeholder (stable)
        self._counters: dict[str, int] = {}
        self._ner = ner_redactor
        # "Complete" once free-text entities are handled (a NER ran or known names
        # were supplied); structured-only de-id leaves names in place.
        self._free_text_handled = ner_redactor is not None

    def _placeholder(self, label: str, original: str) -> str:
        if original in self._reverse:
            return self._reverse[original]
        self._counters[label] = self._counters.get(label, 0) + 1
        ph = f"[{label}_{self._counters[label]}]"
        self._mapping[ph] = original
        self._reverse[original] = ph
        return ph

    def _repl_for(self, spec: _PatternSpec) -> Callable[[re.Match[str]], str]:
        def repl(match: re.Match[str]) -> str:
            original = match.group(0)
            if spec.validator is not None and not spec.validator(original):
                return original
            return self._placeholder(spec.label, original)

        return repl

    def redact(self, text: str, *, known_entities: list[str] | None = None) -> str:
        """De-identify one text against the shared map, returning the redacted text.

        ``known_entities`` are free-text identifiers already known (e.g. party names
        pulled straight from the processo) — redacted deterministically, longest
        first so "João da Silva" is replaced before a bare "Silva".
        """
        out = text
        for spec in _PATTERNS:
            out = spec.pattern.sub(self._repl_for(spec), out)

        entities = list(known_entities or [])
        if known_entities:
            self._free_text_handled = True
        if self._ner is not None:
            entities.extend(self._ner(text))
        for entity in sorted({e for e in entities if e}, key=len, reverse=True):
            if entity in out:
                out = out.replace(entity, self._placeholder("NOME", entity))
        return out

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._mapping)

    @property
    def complete(self) -> bool:
        return self._free_text_handled


def deidentify(text: str, *, ner_redactor: Callable[[str], list[str]] | None = None) -> DeidResult:
    """Replace direct identifiers with reversible placeholders.

    Args:
        text: Raw case text.
        ner_redactor: Optional callable returning entity spans to redact (e.g.
            names/orgs from a LeNER-Br model). Each returned string is replaced.

    Returns:
        :class:`DeidResult` with the de-identified text and the re-id map.
    """
    engine = Deidentifier(ner_redactor=ner_redactor)
    out = engine.redact(text)
    return DeidResult(text=out, mapping=engine.mapping, complete=engine.complete)


def iter_structured_pii(text: str) -> Iterator[tuple[str, str]]:
    """Yield raw structured identifiers still present in ``text``.

    This is intentionally the same detector used by the redactor. It lets cloud
    gates fail closed if a future regex regression leaves CPF/CNPJ/CNJ or another
    high-risk structured identifier in a payload.
    """
    for spec in _PATTERNS:
        for match in spec.pattern.finditer(text):
            value = match.group(0)
            if spec.validator is not None and not spec.validator(value):
                continue
            yield spec.label, value


def contains_structured_pii(text: str) -> bool:
    """Return True when raw structured PII is still present."""
    return next(iter_structured_pii(text), None) is not None


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
    leaked = next(iter_structured_pii(result.text), None)
    if leaked is not None:
        label, _value = leaked
        msg = f"De-identificação incompleta: identificador estruturado residual ({label})."
        raise ValueError(msg)


def reidentify(text: str, mapping: dict[str, str]) -> str:
    """Restore the original identifiers from a de-identification map."""
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text
