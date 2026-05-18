"""Subscription CLI-backed cloud LLM adapter.

LocalCliLLM launches an authenticated desktop CLI such as Claude Code or
Codex CLI, but the model execution is still cloud-side. Inject it only where
the application would normally inject a cloud LLM. It is never a local_llm
replacement and refuses explicit PII-marked calls.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Literal

from juris.llm.base import AbstractLLM, LLMResponse

CliCloudProvider = Literal["claude", "codex"]

_PROVIDER_MODEL_NAMES: dict[CliCloudProvider, str] = {
    "claude": "claude_cli_subscription",
    "codex": "codex_cli_subscription",
}


class LocalCliLLM(AbstractLLM):
    """Cloud-only LLM backend that calls a local subscription CLI.

    Despite the local process boundary, prompts are sent to the provider's
    cloud service through the authenticated CLI. This adapter must only be
    injected as a cloud LLM for non-PII/public-corpus work.
    """

    cloud_only: bool = True
    allows_pii: bool = False

    def __init__(
        self,
        *,
        provider: CliCloudProvider,
        timeout_seconds: float = 180.0,
        cwd: Path | None = None,
    ) -> None:
        if provider not in _PROVIDER_MODEL_NAMES:
            msg = f"Unsupported CLI cloud provider: {provider}"
            raise ValueError(msg)
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._cwd = cwd

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
        """Generate a completion through a subscription CLI.

        Args mirror :class:`AbstractLLM`. ``contains_pii`` is intentionally
        explicit for callers that can label the route; true values fail closed.
        """
        if contains_pii:
            msg = "LocalCliLLM is cloud-only and cannot handle PII-marked prompts."
            raise ValueError(msg)
        if schema:
            msg = "LocalCliLLM does not support structured schema output."
            raise ValueError(msg)

        command, stdin = self._command_and_stdin(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        output = await self._run(command, stdin=stdin)
        return LLMResponse(content=output, model=self.model_name, usage={})

    @property
    def model_name(self) -> str:
        return _PROVIDER_MODEL_NAMES[self._provider]

    @property
    def llm_provider(self) -> str:
        return self.model_name

    def _command_and_stdin(
        self,
        *,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> tuple[list[str], str | None]:
        full_prompt = _compose_prompt(prompt=prompt, system=system)
        if self._provider == "claude":
            command = [
                "claude",
                "--print",
                "--output-format",
                "text",
                "--no-session-persistence",
                "--tools",
                "",
                "--permission-mode",
                "dontAsk",
                full_prompt,
            ]
            return command, None

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as out:
            output_path = out.name
        command = [
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--skip-git-repo-check",
            "--ephemeral",
            "--output-last-message",
            output_path,
            "-",
        ]
        # Codex accepts the prompt on stdin; max_tokens/temperature are not
        # first-class CLI flags here, so the caller-facing values are ignored.
        _ = (max_tokens, temperature)
        return command, full_prompt

    async def _run(self, command: list[str], *, stdin: str | None) -> str:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(self._cwd) if self._cwd else None,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8") if stdin is not None else None),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            msg = f"{self.model_name} timed out after {self._timeout_seconds:.0f}s"
            raise TimeoutError(msg) from exc

        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            msg = f"{self.model_name} failed with exit code {process.returncode}: {err}"
            raise RuntimeError(msg)

        text = stdout.decode("utf-8", errors="replace").strip()
        if self._provider == "codex":
            output_file = Path(command[-2])
            if output_file.exists():
                text = output_file.read_text(encoding="utf-8").strip()
                output_file.unlink(missing_ok=True)
        return text


def _compose_prompt(*, prompt: str, system: str | None) -> str:
    if not system:
        return prompt
    return f"{system.strip()}\n\n{prompt.strip()}"


__all__ = ["CliCloudProvider", "LocalCliLLM"]
