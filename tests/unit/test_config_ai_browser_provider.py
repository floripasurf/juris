"""Preferência declarada do fornecedor de browser (ADR-0018, spec 2026-07-05)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juris.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JURIS_AI_BROWSER_PROVIDER", raising=False)


def test_default_is_none() -> None:
    assert Settings(_env_file=None).ai_browser_provider is None


def test_claude_and_chatgpt_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "claude")
    assert Settings(_env_file=None).ai_browser_provider == "claude"
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "chatgpt")
    assert Settings(_env_file=None).ai_browser_provider == "chatgpt"


def test_invalid_value_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
