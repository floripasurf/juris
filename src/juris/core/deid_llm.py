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
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from juris.core.deid import deidentify, ensure_cloud_safe, reidentify
from juris.llm.base import AbstractLLM, LLMResponse

if TYPE_CHECKING:
    from collections.abc import Callable

_SEP = "\n\x00SYS\x00\n"  # de-id prompt + system together (single re-id map)


class DeidentifyingLLM(AbstractLLM):
    """Wraps a delegate LLM so case PII never leaves de-identified."""

    def __init__(
        self,
        delegate: AbstractLLM,
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
    ) -> LLMResponse:
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


@lru_cache(maxsize=1)
def _legal_ner() -> Any:
    """The shared LeNER-Br NER (loaded once)."""
    from juris.core.ner import LegalNER

    return LegalNER()


def default_ner_redactor() -> Callable[[str], list[str]]:
    """The LeNER-Br name redactor for de-identification (lazy, cached)."""
    return _legal_ner().redact_entities  # type: ignore[no-any-return]


def cloud_safe_llm(delegate: Any, *, require_ner: bool = True) -> DeidentifyingLLM:
    """Wrap a cloud LLM so case PII — including names — is removed before it leaves.

    With ``require_ner`` (default), names go through the LeNER-Br redactor and the
    gate fails closed (``allow_partial=False``) — genuinely cloud-safe, but the
    model must be available. Set ``require_ner=False`` to fall back to structured-
    only de-id (CPF/CNPJ/CNJ/OAB), accepting that names may remain.
    """
    if require_ner:
        return DeidentifyingLLM(delegate, ner_redactor=default_ner_redactor(), allow_partial=False)
    return DeidentifyingLLM(delegate, allow_partial=True)
