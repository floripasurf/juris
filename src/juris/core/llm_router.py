"""LLM routing — decides which provider handles each task based on PII sensitivity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from juris.config import Settings


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class LLMTask(str, Enum):
    ANALYZE = "analyze"       # PII — default local
    DRAFT = "draft"           # PII — default local (cloud with de-identified context)
    RESEARCH = "research"     # Public corpus — cloud OK
    EXTRACT = "extract"       # PII — default local
    CLASSIFY = "classify"     # Depends on input
    REWRITE_QUERY = "rewrite_query"  # Public — cloud OK


# Default routing: tasks bearing PII go local, public-corpus tasks go cloud
_DEFAULT_ROUTES: dict[LLMTask, LLMProvider] = {
    LLMTask.ANALYZE: LLMProvider.OLLAMA,
    LLMTask.DRAFT: LLMProvider.OLLAMA,
    LLMTask.RESEARCH: LLMProvider.ANTHROPIC,
    LLMTask.EXTRACT: LLMProvider.OLLAMA,
    LLMTask.CLASSIFY: LLMProvider.OLLAMA,
    LLMTask.REWRITE_QUERY: LLMProvider.OLLAMA,
}


@dataclass(frozen=True, slots=True)
class LLMRoute:
    """Resolved route for an LLM call."""

    task: LLMTask
    contains_pii: bool
    provider: LLMProvider
    model: str


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

    def route(self, task: LLMTask, contains_pii: bool = False) -> LLMRoute:
        """Resolve which provider and model to use for a given task.

        If the task contains PII, always route to local (Ollama),
        regardless of overrides or defaults.
        """
        if contains_pii:
            provider = LLMProvider.OLLAMA
        else:
            provider = self._overrides.get(task, _DEFAULT_ROUTES[task])

        # Fallback: if Anthropic key is not configured, route to Ollama
        if provider == LLMProvider.ANTHROPIC and not self._settings.anthropic_api_key:
            provider = LLMProvider.OLLAMA

        model = self.MODELS[provider]

        return LLMRoute(
            task=task,
            contains_pii=contains_pii,
            provider=provider,
            model=model,
        )
