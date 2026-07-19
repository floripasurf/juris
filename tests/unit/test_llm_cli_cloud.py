"""Tests for subscription CLI-backed cloud LLM adapters."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from juris.llm.local_cli import LocalCliLLM, _codex_output_file


def test_cli_cloud_adapter_exposes_cloud_provider_identity() -> None:
    llm = LocalCliLLM(provider="claude")

    assert llm.model_name == "claude_cli_subscription"
    assert llm.llm_provider == "claude_cli_subscription"
    assert llm.cloud_only is True
    assert llm.allows_pii is False


def test_cli_cloud_adapter_passes_model_flag_when_set() -> None:
    llm = LocalCliLLM(provider="claude", model="haiku")

    command, stdin = llm._command_and_stdin(
        prompt="analise",
        system=None,
        schema=None,
        max_tokens=128,
        temperature=0.0,
    )

    assert "--model" in command
    assert command[command.index("--model") + 1] == "haiku"
    assert command[-1] == "analise"  # prompt stays last
    assert stdin is None
    assert llm.model_name == "claude_cli_subscription:haiku"


def test_cli_cloud_adapter_omits_model_flag_when_unset() -> None:
    llm = LocalCliLLM(provider="claude")

    command, _ = llm._command_and_stdin(
        prompt="analise", system=None, schema=None, max_tokens=128, temperature=0.0
    )

    assert "--model" not in command
    assert llm.model_name == "claude_cli_subscription"


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


@pytest.mark.asyncio
async def test_cli_cloud_adapter_rejects_invalid_structured_json(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = LocalCliLLM(provider="claude")

    async def fake_run(command: list[str], *, stdin: str | None) -> str:
        return "not json"

    monkeypatch.setattr(llm, "_run", fake_run)

    with pytest.raises(RuntimeError, match="schema"):
        await llm.complete("analise", schema={"type": "object"})


@pytest.mark.asyncio
async def test_schema_raiz_lista_quando_esperado_objeto_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = LocalCliLLM(provider="claude")

    async def fake_run(command: list[str], *, stdin: str | None) -> str:
        return "[1,2,3]"

    monkeypatch.setattr(llm, "_run", fake_run)

    with pytest.raises(RuntimeError, match="schema"):
        await llm.complete("p", schema={"type": "object", "required": ["x"]})


@pytest.mark.asyncio
async def test_schema_json_valido_mas_estrutura_errada_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = LocalCliLLM(provider="claude")

    async def fake_run(command: list[str], *, stdin: str | None) -> str:
        return '{"outra_chave": 1}'

    monkeypatch.setattr(llm, "_run", fake_run)

    with pytest.raises(RuntimeError, match="schema"):
        await llm.complete(
            "p",
            schema={
                "type": "object",
                "required": ["tese"],
                "properties": {"tese": {"type": "string"}},
            },
        )


@pytest.mark.asyncio
async def test_codex_output_file_is_read_and_cleaned_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "codex-output.txt"
    output_path.write_text("final answer\n", encoding="utf-8")
    llm = LocalCliLLM(provider="codex")

    class FakeProcess:
        returncode = 0

        async def communicate(self, stdin: bytes | None) -> tuple[bytes, bytes]:
            return b"stdout fallback", b""

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await llm._run(
        ["codex", "exec", "--output-last-message", str(output_path), "-"],
        stdin="prompt",
    )

    assert result == "final answer"
    assert not output_path.exists()


def test_codex_command_uses_current_exec_flags() -> None:
    llm = LocalCliLLM(provider="codex")

    command, stdin = llm._command_and_stdin(
        prompt="responda ok",
        system=None,
        schema=None,
        max_tokens=128,
        temperature=0.0,
    )

    assert command[:4] == ["codex", "exec", "--sandbox", "read-only"]
    assert "--ask-for-approval" not in command
    assert "never" not in command
    assert "--skip-git-repo-check" in command
    assert "--ephemeral" in command
    assert command[-1] == "-"
    assert stdin == "responda ok"


def test_codex_command_modelo_effort_binario() -> None:
    llm = LocalCliLLM(
        provider="codex",
        model="gpt-5.5",
        reasoning_effort="low",
        binary="/opt/homebrew/bin/codex",
    )

    command, stdin = llm._command_and_stdin(
        prompt="p", system=None, schema=None, max_tokens=64, temperature=0.0
    )
    try:
        assert command[0] == "/opt/homebrew/bin/codex"
        i = command.index("-m")
        assert command[i + 1] == "gpt-5.5"
        j = command.index("-c")
        assert command[j + 1] == 'model_reasoning_effort="low"'
        assert stdin == "p"
    finally:
        _codex_output_file(command).unlink(missing_ok=True)  # teste não vaza tmp


def test_claude_command_usa_binario_customizado() -> None:
    llm = LocalCliLLM(provider="claude", binary="/opt/homebrew/bin/claude")

    command, _ = llm._command_and_stdin(
        prompt="p", system=None, schema=None, max_tokens=64, temperature=0.0
    )

    assert command[0] == "/opt/homebrew/bin/claude"


@pytest.mark.asyncio
async def test_codex_output_file_is_cleaned_up_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "codex-output.txt"
    output_path.write_text("partial answer\n", encoding="utf-8")
    llm = LocalCliLLM(provider="codex")

    class FakeProcess:
        returncode = 2

        async def communicate(self, stdin: bytes | None) -> tuple[bytes, bytes]:
            return b"", b"boom"

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="boom"):
        await llm._run(
            ["codex", "exec", "--output-last-message", str(output_path), "-"],
            stdin="prompt",
        )

    assert not output_path.exists()


def test_cli_cloud_adapter_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported CLI cloud provider"):
        LocalCliLLM(provider="ollama")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_timeout_mata_grupo_de_processos(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real, cheap subprocess (`sh -c sleep`) must be killed group-wide on timeout."""
    llm = LocalCliLLM(provider="claude", timeout_seconds=0.2, binary="/bin/sh")

    def fake_command_and_stdin(**kwargs: object) -> tuple[list[str], str | None]:
        return ["/bin/sh", "-c", "sleep 5"], None

    monkeypatch.setattr(llm, "_command_and_stdin", fake_command_and_stdin)

    real_create_subprocess_exec = asyncio.create_subprocess_exec
    spawned: dict[str, asyncio.subprocess.Process] = {}

    async def capturing_create_subprocess_exec(
        *args: str, **kwargs: object
    ) -> asyncio.subprocess.Process:
        process = await real_create_subprocess_exec(*args, **kwargs)
        spawned["process"] = process
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capturing_create_subprocess_exec)

    with pytest.raises(TimeoutError):
        await llm.complete("p")

    pid = spawned["process"].pid
    with pytest.raises(ProcessLookupError):
        os.killpg(os.getpgid(pid), 0)
