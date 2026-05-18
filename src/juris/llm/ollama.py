"""Ollama LLM backend — for PII-bearing tasks (runs locally)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM, LLMResponse

logger = get_logger(__name__)


class OllamaLLM(AbstractLLM):
    """Ollama local LLM backend."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3:8b",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        # Ollama supports JSON mode via format parameter
        if schema:
            payload["format"] = "json"

        logger.info("ollama_call", model=self._model, has_schema=bool(schema))

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("message", {}).get("content", "")

        # Try to parse structured output
        structured = None
        if schema and content:
            try:
                structured = json.loads(content)
            except json.JSONDecodeError:
                pass

        # Ollama provides eval_count and prompt_eval_count
        usage = {
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0),
        }

        return LLMResponse(
            content=content,
            model=self._model,
            usage=usage,
            structured=structured,
        )

    @property
    def model_name(self) -> str:
        return self._model
