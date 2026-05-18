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


@pytest.mark.asyncio
async def test_cli_cloud_adapter_accepts_structured_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = LocalCliLLM(provider="claude")
    captured: dict[str, object] = {}

    async def fake_run(command: list[str], *, stdin: str | None) -> str:
        captured["command"] = command
        captured["stdin"] = stdin
        return '{"issues":[]}'

    monkeypatch.setattr(llm, "_run", fake_run)

    response = await llm.complete(
        "analise",
        system="sistema",
        schema={"type": "object", "properties": {"issues": {"type": "array"}}},
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert response.content == '{"issues":[]}'
    assert response.structured == {"issues": []}
    assert command[:3] == ["claude", "--print", "--output-format"]
    assert captured["stdin"] is None
    assert "Responda somente com JSON valido" in command[-1]
    assert '"issues"' in command[-1]


def test_cli_cloud_adapter_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported CLI cloud provider"):
        LocalCliLLM(provider="ollama")  # type: ignore[arg-type]
