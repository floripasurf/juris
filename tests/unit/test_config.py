"""Tests for pydantic Settings env bindings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juris.config import Settings


def test_web_runtime_settings_read_juris_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_API_RATE_LIMIT_PER_MINUTE", "42")
    monkeypatch.setenv("JURIS_API_EXPENSIVE_RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("JURIS_WS_AGENT_RELAY_RATE_LIMIT_PER_MINUTE", "9")
    monkeypatch.setenv("JURIS_RATE_LIMIT_REDIS_URL", "redis://localhost:6380/9")
    monkeypatch.setenv("JURIS_CONNECT_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("JURIS_TST_INTEIRO_TEOR_ENABLED", "true")

    settings = Settings(_env_file=None)

    assert settings.api_rate_limit_per_minute == 42
    assert settings.api_expensive_rate_limit_per_minute == 7
    assert settings.ws_agent_relay_rate_limit_per_minute == 9
    assert settings.rate_limit_redis_url == "redis://localhost:6380/9"
    assert settings.connect_timeout_seconds == 1200
    assert settings.tst_inteiro_teor_enabled is True


def test_connect_timeout_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_CONNECT_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
