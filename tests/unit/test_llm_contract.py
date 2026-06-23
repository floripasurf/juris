"""Tests for the shared LLM backend contract."""

from __future__ import annotations

from inspect import Parameter, signature

from juris.llm.base import AbstractLLM
from juris.llm.claude import ClaudeLLM
from juris.llm.local_cli import LocalCliLLM
from juris.llm.ollama import OllamaLLM


def test_llm_complete_contract_includes_pii_marker() -> None:
    implementations = [AbstractLLM, ClaudeLLM, LocalCliLLM, OllamaLLM]

    for implementation in implementations:
        params = signature(implementation.complete).parameters
        assert "contains_pii" in params
        assert params["contains_pii"].kind is Parameter.KEYWORD_ONLY
        assert params["contains_pii"].default is False
