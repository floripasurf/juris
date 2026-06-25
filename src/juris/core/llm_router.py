"""LLM routing — decides which provider handles each task based on PII sensitivity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from juris.core.deid import deidentify, ensure_cloud_safe

if TYPE_CHECKING:
    from collections.abc import Callable

    from juris.config import Settings


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class PIIMode(str, Enum):
    """How PII-bearing tasks are handled (ADR-0016)."""

    LOCAL_RAW = "local_raw"  # default — keep on the local model, raw
    CLOUD_DEID = "cloud_deid"  # de-identify, then use the cloud model
    CLOUD_RAW = "cloud_raw"  # cloud, raw — explicit opt-in (consent + DPA)


class LLMTask(str, Enum):
    ANALYZE = "analyze"       # PII — default local
    DRAFT = "draft"           # PII — default local (cloud with de-identified context)
    RESEARCH = "research"     # Public corpus — cloud OK
    EXTRACT = "extract"       # PII — default local
    CLASSIFY = "classify"     # Depends on input
    REWRITE_QUERY = "rewrite_query"  # Public — cloud OK
    ANALYZE_DEFESA = "analyze_defesa"  # PII — default local


# Default routing: tasks bearing PII go local, public-corpus tasks go cloud
_DEFAULT_ROUTES: dict[LLMTask, LLMProvider] = {
    LLMTask.ANALYZE: LLMProvider.OLLAMA,
    LLMTask.DRAFT: LLMProvider.OLLAMA,
    LLMTask.RESEARCH: LLMProvider.ANTHROPIC,
    LLMTask.EXTRACT: LLMProvider.OLLAMA,
    LLMTask.CLASSIFY: LLMProvider.OLLAMA,
    LLMTask.REWRITE_QUERY: LLMProvider.OLLAMA,
    LLMTask.ANALYZE_DEFESA: LLMProvider.OLLAMA,
}


@dataclass(frozen=True, slots=True)
class LLMRoute:
    """Resolved route for an LLM call."""

    task: LLMTask
    contains_pii: bool
    provider: LLMProvider
    model: str
    deidentify: bool = False  # caller must de-identify input + re-identify output


class LLMRouter:
    """Routes LLM tasks to the appropriate provider based on PII sensitivity and config."""

    # Model defaults per provider
    MODELS: dict[LLMProvider, str] = {
        LLMProvider.ANTHROPIC: "claude-sonnet-4-6",
        LLMProvider.OLLAMA: "qwen3:latest",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._overrides: dict[LLMTask, LLMProvider] = {}

    def override(self, task: LLMTask, provider: LLMProvider) -> None:
        """Override the default route for a task."""
        self._overrides[task] = provider

    def route(
        self,
        task: LLMTask,
        contains_pii: bool = False,
        pii_mode: PIIMode = PIIMode.LOCAL_RAW,
    ) -> LLMRoute:
        """Resolve which provider/model to use, and whether to de-identify.

        PII handling follows ``pii_mode`` (ADR-0016): ``LOCAL_RAW`` keeps it on
        the local model; ``CLOUD_DEID`` uses the cloud model on de-identified
        text; ``CLOUD_RAW`` uses the cloud model raw (explicit opt-in).
        """
        deidentify = False
        if contains_pii:
            if pii_mode is PIIMode.CLOUD_DEID:
                provider = LLMProvider.ANTHROPIC
                deidentify = True
            elif pii_mode is PIIMode.CLOUD_RAW:
                provider = LLMProvider.ANTHROPIC
            else:  # LOCAL_RAW
                provider = LLMProvider.OLLAMA
        else:
            provider = self._overrides.get(task, _DEFAULT_ROUTES[task])

        # Fallback: no Anthropic key → local (and nothing to de-identify there).
        if provider == LLMProvider.ANTHROPIC and not self._settings.anthropic_api_key:
            provider = LLMProvider.OLLAMA
            deidentify = False

        return LLMRoute(
            task=task,
            contains_pii=contains_pii,
            provider=provider,
            model=self.MODELS[provider],
            deidentify=deidentify,
        )

    def prepare_payload(
        self,
        route: LLMRoute,
        prompt: str,
        *,
        ner_redactor: Callable[[str], list[str]] | None = None,
        allow_partial: bool = False,
    ) -> tuple[str, dict[str, str]]:
        """De-identify the prompt when the route demands it; gate cloud safety.

        Returns the (possibly de-identified) text and the re-identification map
        the caller applies to the model's response. When ``route.deidentify`` is
        False, returns the prompt unchanged with an empty map. Raises if the
        de-identification is only partial (structured-only, no NER) and the
        caller didn't explicitly opt in — cloud calls fail closed (ADR-0016).
        """
        if not route.deidentify:
            return prompt, {}
        result = deidentify(prompt, ner_redactor=ner_redactor)
        ensure_cloud_safe(result, allow_partial=allow_partial)
        return result.text, result.mapping
