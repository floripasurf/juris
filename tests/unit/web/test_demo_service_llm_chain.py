"""CLI-signature draft chain (Task 2 canary): off by default, allowlist-gated, serialized.

The chain drives a human's subscription CLI (codex/claude), always behind fail-closed
de-id (ADR-0016). It must stay inert unless JURIS_DRAFT_BACKEND=cli AND the tenant is on
the (empty-by-default) allowlist — a trial tenant must never reach it, and concurrent
draft calls must never overlap through the same signed-in session.
"""

from __future__ import annotations

import asyncio

import pytest

from juris.llm.base import AbstractLLM, LLMResponse


def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import juris.config as config

    monkeypatch.setattr(config, "_settings", None)


def _stub_ner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid loading the real LeNER-Br model; any non-None redactor satisfies fail-closed."""
    from juris.core import deid_llm

    monkeypatch.setattr(deid_llm, "default_ner_redactor", lambda: (lambda _t: []))


@pytest.mark.asyncio
async def test_build_cli_chain_composes_codex_then_haiku_then_local_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) DeidentifyingLLM(codex) -> FallbackLLM -> DeidentifyingLLM(haiku) -> local Ollama
    (no de-id — on-device)."""
    _reset_settings(monkeypatch)
    _stub_ner(monkeypatch)
    from juris.core.deid_llm import DeidentifyingLLM
    from juris.core.fallback_llm import FallbackLLM
    from juris.llm.local_cli import LocalCliLLM
    from juris.llm.ollama import OllamaLLM
    from juris.web import demo_service

    chain = demo_service._build_cli_chain()

    assert isinstance(chain, FallbackLLM)
    assert isinstance(chain._primary, DeidentifyingLLM)
    assert isinstance(chain._primary._delegate, LocalCliLLM)
    assert chain._primary._delegate._provider == "codex"
    assert chain._primary._ner is not None  # fail-closed NER on the codex leg
    assert chain._primary._allow_partial is False

    inner = chain._fallback
    assert isinstance(inner, FallbackLLM)
    assert isinstance(inner._primary, DeidentifyingLLM)
    assert isinstance(inner._primary._delegate, LocalCliLLM)
    assert inner._primary._delegate._provider == "claude"
    assert inner._primary._ner is not None  # fail-closed NER on the haiku leg
    assert inner._primary._allow_partial is False

    # Terminal local step: on-device Ollama, deliberately NOT wrapped in DeidentifyingLLM.
    assert isinstance(inner._fallback, OllamaLLM)


@pytest.mark.asyncio
async def test_build_cli_chain_uses_empty_tempdir_cwd_for_cli_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LocalCliLLM legs get an empty tempdir as cwd (codex/claude can't read case files)."""
    _reset_settings(monkeypatch)
    _stub_ner(monkeypatch)
    from juris.web import demo_service

    chain = demo_service._build_cli_chain()
    codex_leg = chain._primary._delegate
    haiku_leg = chain._fallback._primary._delegate

    for leg in (codex_leg, haiku_leg):
        cwd = leg._cwd
        assert cwd is not None
        assert cwd.exists()
        assert not any(cwd.iterdir())  # empty


def test_build_llm_outside_allowlist_returns_plain_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b) backend=cli but tenant_id not in the allowlist -> plain Ollama, not the chain."""
    from juris.llm.ollama import OllamaLLM
    from juris.web import demo_service

    monkeypatch.delenv("JURIS_AI_PREFERENCE", raising=False)
    monkeypatch.setenv("JURIS_DRAFT_BACKEND", "cli")
    monkeypatch.setenv("JURIS_CLI_LLM_TENANTS", "escritorio-piloto")
    _reset_settings(monkeypatch)

    llm = demo_service._build_llm(use_cloud=False, tenant_id="trial_x")

    assert isinstance(llm, OllamaLLM)
    assert not isinstance(llm, demo_service._SerializedLLM)


def test_build_llm_in_allowlist_returns_serialized_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """(c) backend=cli and tenant_id on the allowlist -> the serialized CLI chain."""
    from juris.core.fallback_llm import FallbackLLM
    from juris.web import demo_service

    monkeypatch.delenv("JURIS_AI_PREFERENCE", raising=False)
    monkeypatch.setenv("JURIS_DRAFT_BACKEND", "cli")
    monkeypatch.setenv("JURIS_CLI_LLM_TENANTS", "escritorio-piloto")
    _reset_settings(monkeypatch)
    _stub_ner(monkeypatch)

    llm = demo_service._build_llm(use_cloud=False, tenant_id="escritorio-piloto")

    assert isinstance(llm, demo_service._SerializedLLM)
    assert isinstance(llm._delegate, FallbackLLM)


def test_build_llm_default_backend_never_touches_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate stays inert even inside the allowlist when draft_backend is still 'ollama'."""
    from juris.llm.ollama import OllamaLLM
    from juris.web import demo_service

    monkeypatch.delenv("JURIS_AI_PREFERENCE", raising=False)
    monkeypatch.delenv("JURIS_DRAFT_BACKEND", raising=False)
    monkeypatch.setenv("JURIS_CLI_LLM_TENANTS", "escritorio-piloto")
    _reset_settings(monkeypatch)

    llm = demo_service._build_llm(use_cloud=False, tenant_id="escritorio-piloto")

    assert isinstance(llm, OllamaLLM)


class _EventGatedLLM(AbstractLLM):
    """Records call order; the first call blocks on ``release`` until told to proceed."""

    def __init__(self, release: asyncio.Event) -> None:
        self._release = release
        self.started: list[str] = []

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, object] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        *,
        contains_pii: bool = False,
    ) -> LLMResponse:
        self.started.append(prompt)
        if prompt == "first":
            await self._release.wait()
        return LLMResponse(content=prompt, model="fake")

    @property
    def model_name(self) -> str:
        return "fake"


@pytest.mark.asyncio
async def test_serialized_llm_runs_concurrent_calls_one_at_a_time() -> None:
    """(d) Two concurrent calls through the wrapper never overlap (global concurrency 1)."""
    from juris.web import demo_service

    release = asyncio.Event()
    fake = _EventGatedLLM(release)
    wrapped = demo_service._SerializedLLM(fake)

    first_task = asyncio.create_task(wrapped.complete("first"))
    await asyncio.sleep(0)  # let "first" acquire the semaphore and block on release

    second_task = asyncio.create_task(wrapped.complete("second"))
    await asyncio.sleep(0)  # "second" must NOT have started — it's queued behind the semaphore

    assert fake.started == ["first"]

    release.set()
    await asyncio.gather(first_task, second_task)
    assert fake.started == ["first", "second"]
