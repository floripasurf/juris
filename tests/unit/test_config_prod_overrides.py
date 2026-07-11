"""ENVIRONMENT=prod não pode mascarar env vars esquecidas com defaults localhost.

Port adaptado do PR #3 (`fix/require-prod-env-overrides`, auditoria Atlas 2026-05-21):
o validador literal falharia fechado sempre que uma URL localhost sobrevivesse em
prod, o que derrubaria o piloto SQLite-first (que legitimamente não define
DATABASE_URL/QDRANT_URL/REDIS_URL). Em main o comportamento é: reportar os
vazamentos (`dev_default_leaks`), avisar por log, e só falhar fechado com
`JURIS_STRICT_PROD_URLS=1` (deploy docker que realmente usa esses serviços).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juris.config import Settings

_URL_ENV_VARS = (
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
    "QDRANT_URL",
    "REDIS_URL",
    "OLLAMA_URL",
    "JURIS_STRICT_PROD_URLS",
    "ENVIRONMENT",
)

_PROD_OVERRIDE_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/juris",
    "DATABASE_URL_SYNC": "postgresql+psycopg://u:p@db:5432/juris",
    "QDRANT_URL": "http://qdrant:6333",
    "REDIS_URL": "redis://redis:6379/0",
    "OLLAMA_URL": "http://ollama:11434",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove env vars que poderiam vazar do ambiente real para o teste."""
    for var in _URL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_prod_with_defaults_reports_leaks() -> None:
    settings = Settings(environment="prod", _env_file=None)
    assert sorted(settings.dev_default_leaks()) == [
        "database_url",
        "database_url_sync",
        "ollama_url",
        "qdrant_url",
        "redis_url",
    ]


def test_prod_non_strict_loads_despite_leaks() -> None:
    """Default (não-strict): carrega mesmo com defaults localhost — não derruba o piloto."""
    settings = Settings(environment="prod", _env_file=None)
    assert settings.environment.value == "prod"
    assert settings.dev_default_leaks()  # há vazamentos, mas não bloqueou


def test_prod_strict_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_STRICT_PROD_URLS", "1")
    with pytest.raises(ValidationError) as exc:
        Settings(environment="prod", _env_file=None)
    message = str(exc.value)
    for name in ("database_url", "qdrant_url", "redis_url", "ollama_url"):
        assert name in message


def test_prod_strict_mode_passes_with_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_STRICT_PROD_URLS", "1")
    for var, value in _PROD_OVERRIDE_ENV.items():
        monkeypatch.setenv(var, value)
    settings = Settings(environment="prod", _env_file=None)
    assert settings.dev_default_leaks() == []


def test_dev_defaults_load_and_report_nothing() -> None:
    settings = Settings(environment="dev", _env_file=None)
    assert settings.dev_default_leaks() == []
