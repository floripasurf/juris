"""Shared test fixtures."""

import importlib

import pytest


@pytest.fixture(autouse=True)
def _clear_process_wide_caches():
    """Reset process-wide config/routing caches so env and rate buckets don't leak
    between tests."""
    from juris import config
    from juris.api.agent_config import _load_agent_bindings

    web_app = importlib.import_module("juris.web.app")

    _load_agent_bindings.cache_clear()
    config._settings = None  # noqa: SLF001 - test isolation for Settings singleton
    web_app._api_rate_limiter.cache_clear()
    web_app._api_expensive_rate_limiter.cache_clear()
    web_app._ws_agent_relay_rate_limiter.cache_clear()
    yield
    _load_agent_bindings.cache_clear()
    config._settings = None  # noqa: SLF001 - test isolation for Settings singleton
    web_app._api_rate_limiter.cache_clear()
    web_app._api_expensive_rate_limiter.cache_clear()
    web_app._ws_agent_relay_rate_limiter.cache_clear()
