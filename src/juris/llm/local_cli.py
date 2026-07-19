"""Subscription CLI-backed cloud LLM adapter.

LocalCliLLM launches an authenticated Claude Code CLI, but the model execution
is still cloud-side. Inject it only where
the application would normally inject a cloud LLM. It is never a local_llm
replacement and refuses explicit PII-marked calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any, Literal

from juris.llm.base import AbstractLLM, LLMResponse

CliCloudProvider = Literal["claude"]

_PROVIDER_MODEL_NAMES: dict[CliCloudProvider, str] = {
    "claude": "claude_cli_subscription",
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
        model: str | None = None,
        timeout_seconds: float = 180.0,
        cwd: Path | None = None,
        binary: str | None = None,
    ) -> None:
        if provider not in _PROVIDER_MODEL_NAMES:
            msg = f"Unsupported CLI cloud provider: {provider}"
            raise ValueError(msg)
        self._provider = provider
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._cwd = cwd
        self._binary = binary

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

        Raises:
            ValueError: If ``contains_pii`` is True (this adapter is cloud-only).
            RuntimeError: If ``schema`` was requested and the CLI output is not
                valid JSON, or the parsed JSON does not conform to ``schema``
                (wrong root type, or missing ``required`` keys).
        """
        if contains_pii:
            msg = "LocalCliLLM is cloud-only and cannot handle PII-marked prompts."
            raise ValueError(msg)
        command, stdin = self._command_and_stdin(
            prompt=prompt,
            system=system,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        output = await self._run(command, stdin=stdin)
        structured = None
        usage: dict[str, int] = {}
        if schema and output:
            try:
                structured = json.loads(output)
            except json.JSONDecodeError as exc:
                msg = f"{self.model_name} violou o schema: saída não é JSON válido."
                raise RuntimeError(msg) from exc
            self._validate_structured(schema, structured)
        return LLMResponse(
            content=output,
            model=self.model_name,
            usage=usage,
            structured=structured,
        )

    def _validate_structured(self, schema: dict[str, Any], structured: Any) -> None:
        """Check the parsed JSON against a minimal subset of JSON Schema.

        Only checks the root type (when ``type: object``) and presence of
        ``required`` keys — enough to catch a malformed structured response
        without pulling in a jsonschema dependency.
        """
        if schema.get("type") == "object" and not isinstance(structured, dict):
            msg = f"{self.model_name} violou o schema: raiz da resposta não é um objeto."
            raise RuntimeError(msg)
        required = schema.get("required", [])
        if required and isinstance(structured, dict):
            missing = [key for key in required if key not in structured]
            if missing:
                msg = f"{self.model_name} violou o schema: faltam as chaves obrigatórias {missing}."
                raise RuntimeError(msg)

    @property
    def model_name(self) -> str:
        base = _PROVIDER_MODEL_NAMES[self._provider]
        return f"{base}:{self._model}" if self._model else base

    @property
    def llm_provider(self) -> str:
        return self.model_name

    def _command_and_stdin(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: dict[str, Any] | None,
        max_tokens: int,
        temperature: float,
    ) -> tuple[list[str], str | None]:
        full_prompt = _compose_prompt(prompt=prompt, system=system, schema=schema)
        command = [
            self._binary or "claude",
            "--print",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--safe-mode",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
        ]
        if self._model:
            command += ["--model", self._model]
        command.append(full_prompt)
        _ = (max_tokens, temperature)  # Claude CLI has no direct equivalents.
        return command, None

    async def _run(self, command: list[str], *, stdin: str | None) -> str:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(self._cwd) if self._cwd else None,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin.encode("utf-8") if stdin is not None else None),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            _kill_process_group(process)
            await process.wait()
            msg = f"{self.model_name} timed out after {self._timeout_seconds:.0f}s"
            raise TimeoutError(msg) from exc

        if process.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            msg = f"{self.model_name} failed with exit code {process.returncode}: {err}"
            raise RuntimeError(msg)

        return stdout.decode("utf-8", errors="replace").strip()


def _compose_prompt(
    *,
    prompt: str,
    system: str | None,
    schema: dict[str, Any] | None,
) -> str:
    parts: list[str] = []
    if system:
        parts.append(system.strip())
    parts.append(prompt.strip())
    if schema:
        parts.append(
            "Responda somente com JSON valido que siga este JSON Schema. "
            "Nao inclua markdown, comentarios ou texto fora do JSON.\n"
            f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
        )
    return "\n\n".join(parts)


def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    """Kill the whole process group spawned for ``process``.

    ``process`` was started with ``start_new_session=True``, so its pid is
    also its process group id; this reaches children the CLI may have
    forked (e.g. the underlying model runner) instead of leaving orphans
    behind. Falls back to killing just the process if the group is already
    gone (e.g. it exited between the timeout and this call).
    """
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except ProcessLookupError:
        process.kill()


__all__ = ["CliCloudProvider", "LocalCliLLM"]
