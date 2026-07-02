"""LLM fallback — the lawyer's browser session first, a backup if it fails (ADR-0018).

The browser session (the lawyer's own Claude/ChatGPT subscription) is preferred: no
API cost, frontier quality, PII stays in their perimeter. But a browser session is
fragile — DOM changes, timeouts, a logged-out tab. This wrapper tries the primary and,
on ANY failure, falls back to a backup LLM (cloud de-identified, or local), so a broken
session degrades gracefully instead of blocking the lawyer.

Both the primary and the backup MUST already be de-identified where they leave the
perimeter — wrap each in DeidentifyingLLM so PII never crosses on either path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM, LLMResponse

logger = get_logger(__name__)


class FallbackLLM(AbstractLLM):
    """Try ``primary``; on any error, fall back to ``fallback`` (both de-id'd upstream)."""

    def __init__(
        self,
        primary: AbstractLLM,
        fallback: AbstractLLM,
        *,
        on_fallback: Callable[[Exception], None] | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._on_fallback = on_fallback

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        try:
            return await self._primary.complete(
                prompt, system=system, schema=schema, max_tokens=max_tokens, temperature=temperature
            )
        except Exception as exc:  # noqa: BLE001 — any primary failure ⇒ degrade to the backup
            logger.warning(
                "llm_fallback",
                primary=self._primary.model_name,
                fallback=self._fallback.model_name,
                error=str(exc),
                exception_type=exc.__class__.__name__,
            )
            if self._on_fallback is not None:
                self._on_fallback(exc)
            return await self._fallback.complete(
                prompt, system=system, schema=schema, max_tokens=max_tokens, temperature=temperature
            )

    @property
    def model_name(self) -> str:
        return f"{self._primary.model_name}→{self._fallback.model_name}"


def build_ai_of_preference(
    browser_llm: AbstractLLM,
    fallback: AbstractLLM,
    *,
    ner_redactor: Callable[[str], list[str]] | None = None,
    allow_partial: bool = False,
    fallback_is_local: bool = False,
) -> AbstractLLM:
    """Compose the ADR-0018 AI-of-preference: a **de-identified** browser session with a
    fallback for when it fails.

    BOTH paths are de-identified by default: the browser session AND the fallback are
    each wrapped in ``DeidentifyingLLM``. This matters because failover is exactly where
    the guarantee would otherwise invert — a broken browser session must not dump raw
    PII to the cloud fallback. By default this path fails closed unless a NER redactor
    is supplied; use ``allow_partial=True`` only for a documented structured-only
    consent/DPA path. Set ``fallback_is_local=True`` only when the fallback is an
    on-device model (PII stays in-perimeter), to skip its redaction.
    """
    from juris.core.deid_llm import DeidentifyingLLM

    safe_browser = DeidentifyingLLM(browser_llm, allow_partial=allow_partial, ner_redactor=ner_redactor)
    safe_fallback = (
        fallback
        if fallback_is_local
        else DeidentifyingLLM(fallback, allow_partial=allow_partial, ner_redactor=ner_redactor)
    )
    return FallbackLLM(safe_browser, safe_fallback)
