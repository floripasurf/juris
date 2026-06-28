"""De-identifying LLM wrapper — makes the cloud path cloud-safe (ADR-0016).

The agents (drafter, reviewer, researcher) call ``self._llm.complete`` directly.
When the underlying provider is a cloud model, raw case PII would leave the
perimeter. This wrapper sits in front of any LLM: it de-identifies the prompt
(and system) before delegating, enforces the cloud-safety gate, and re-identifies
the model's response for the caller — transparently, without touching the agents.

Provider-agnostic by design: it duck-types the delegate (``complete`` +
``model_name``) and uses ``dataclasses.replace`` on the response, so it needs no
import of the (local, gitignored) LLM engine.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from juris.core.deid import deidentify, ensure_cloud_safe, reidentify

if TYPE_CHECKING:
    from collections.abc import Callable

_SEP = "\n\x00SYS\x00\n"  # de-id prompt + system together (single re-id map)


class DeidentifyingLLM:
    """Wraps a delegate LLM so case PII never leaves de-identified."""

    def __init__(
        self,
        delegate: Any,
        *,
        allow_partial: bool = True,
        ner_redactor: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._delegate = delegate
        self._allow_partial = allow_partial
        self._ner = ner_redactor

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> Any:
        deid = deidentify(prompt + _SEP + (system or ""), ner_redactor=self._ner)
        ensure_cloud_safe(deid, allow_partial=self._allow_partial)
        deid_prompt, _, deid_system = deid.text.partition(_SEP)

        response = await self._delegate.complete(
            deid_prompt,
            system=deid_system if system else None,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return replace(response, content=reidentify(response.content, deid.mapping))

    @property
    def model_name(self) -> str:
        return str(self._delegate.model_name)
