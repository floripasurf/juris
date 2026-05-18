"""Tests for subscription CLI-backed cloud LLM adapters."""

from __future__ import annotations

import pytest

from juris.llm.local_cli import LocalCliLLM


def test_cli_cloud_adapter_exposes_cloud_provider_identity() -> None:
    llm = LocalCliLLM(provider="claude")

    assert llm.model_name == "claude_cli_subscription"
    assert llm.llm_provider == "claude_cli_subscription"
    assert llm.cloud_only is True
    assert llm.allows_pii is False


@pytest.mark.asyncio
async def test_cli_cloud_adapter_refuses_explicit_pii_context() -> None:
    llm = LocalCliLLM(provider="claude")

    with pytest.raises(ValueError, match="PII"):
        await llm.complete("numero CNJ real", contains_pii=True)


def test_cli_cloud_adapter_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported CLI cloud provider"):
        LocalCliLLM(provider="ollama")  # type: ignore[arg-type]
