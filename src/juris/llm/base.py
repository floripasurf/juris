"""Abstract LLM interface — cloud and local implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Response from an LLM call."""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens
    structured: dict[str, Any] | None = None  # Parsed JSON if schema was provided


class AbstractLLM(ABC):
    """Interface for LLM backends."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        *,
        contains_pii: bool = False,
    ) -> LLMResponse:
        """Generate a completion.

        Args:
            prompt: User message.
            system: System prompt.
            schema: JSON schema for structured output (optional).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            contains_pii: Whether the prompt contains PII-sensitive case data.

        Returns:
            LLMResponse with content and metadata.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
