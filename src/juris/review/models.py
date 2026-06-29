from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReviewDimension(str, Enum):
    COMPLETENESS = "completeness"
    AUTHORITY = "authority"
    COUNTERARGUMENTS = "counterarguments"
    STRUCTURE = "structure"
    COMPLIANCE = "compliance"


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    SUGGESTION = "suggestion"


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    dimension: ReviewDimension
    severity: IssueSeverity
    title: str
    description: str
    line_anchor: str | None = None
    suggestion: str | None = None
    citations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CitationRef:
    raw_text: str
    normalized: str
    found_in_repertory: bool
    repertory_match: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    petition_text: str
    petition_type: str | None = None
    numero_cnj: str | None = None
    tribunal: str | None = None


@dataclass(slots=True)
class ReviewReport:
    request: ReviewRequest
    issues: list[ReviewIssue] = field(default_factory=list)
    citations_found: list[CitationRef] = field(default_factory=list)
    dimensions_analyzed: list[ReviewDimension] = field(default_factory=list)
    llm_calls: int = 0
    retrieval_calls: int = 0
    model_used: str = ""
    prompt_version: str = "v1"
    duration_seconds: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    @property
    def important_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.IMPORTANT)

    @property
    def suggestion_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.SUGGESTION)

    def to_markdown(self) -> str:
        """Render the review report as structured Markdown."""
        # Build header
        lines = ["# Revisao: petição"]
        if self.request.numero_cnj:
            lines[0] += f" — {self.request.numero_cnj}"

        meta_parts = []
        if self.request.numero_cnj:
            meta_parts.append(f"**Processo:** {self.request.numero_cnj}")
        if self.request.tribunal:
            meta_parts.append(f"**Tribunal:** {self.request.tribunal}")
        meta_parts.append(f"**Modelo:** {self.model_used}")
        meta_parts.append(f"**Duracao:** {self.duration_seconds:.1f}s")
        lines.append(" | ".join(meta_parts))
        lines.append("")

        # Summary
        lines.append("## Resumo")
        lines.append(f"- {self.critical_count} problemas criticos")
        lines.append(f"- {self.important_count} problemas importantes")
        lines.append(f"- {self.suggestion_count} sugestoes")
        lines.append("")

        # Citations
        if self.citations_found:
            verified = sum(1 for c in self.citations_found if c.found_in_repertory)
            not_verified = len(self.citations_found) - verified
            lines.append(f"## Citacoes ({len(self.citations_found)} encontradas, {not_verified} nao verificadas)")
            lines.append("| Citacao | Status |")
            lines.append("|---------|--------|")
            for c in self.citations_found:
                status = "Verificada" if c.found_in_repertory else "Nao encontrada no repositorio"
                lines.append(f"| {c.raw_text} | {status} |")
            lines.append("")

        # Issues by severity
        lines.append("## Problemas")
        lines.append("")

        severity_icons = {
            IssueSeverity.CRITICAL: "CRITICAL",
            IssueSeverity.IMPORTANT: "IMPORTANT",
            IssueSeverity.SUGGESTION: "SUGGESTION",
        }

        for issue in self.issues:
            icon = severity_icons[issue.severity]
            lines.append(f"### [{icon}] {issue.title}")
            lines.append(f"**Dimensao:** {issue.dimension.value}")
            if issue.line_anchor:
                lines.append(f"**Trecho:** \"{issue.line_anchor}\"")
            lines.append(issue.description)
            if issue.suggestion:
                lines.append(f"**Sugestao:** {issue.suggestion}")
            if issue.citations:
                lines.append(f"**Fontes:** {', '.join(issue.citations)}")
            lines.append("")

        return "\n".join(lines)
