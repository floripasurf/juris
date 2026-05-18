"""Claude API LLM backend — for non-PII tasks."""

from __future__ import annotations

import json
from typing import Any

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM, LLMResponse

logger = get_logger(__name__)


class ClaudeLLM(AbstractLLM):
    """Anthropic Claude API backend."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._api_key)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        if system:
            kwargs["system"] = system

        # Use tools for structured output
        if schema:
            kwargs["tools"] = [{
                "name": "analysis_result",
                "description": "Structured analysis output",
                "input_schema": schema,
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": "analysis_result"}

        logger.info("claude_call", model=self._model, has_schema=bool(schema))
        response = await client.messages.create(**kwargs)

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        # Extract content
        content = ""
        structured = None
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                structured = block.input
                content = json.dumps(block.input, ensure_ascii=False)

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            structured=structured,
        )

    @property
    def model_name(self) -> str:
        return self._model
