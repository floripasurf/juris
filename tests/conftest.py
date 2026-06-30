"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _clear_agent_bindings_cache():
    """Reset the per-tenant agent-binding cache so JURIS_AGENTS_FILE doesn't leak
    between tests (the lru_cache is process-wide)."""
    from juris.api.agent_config import _load_agent_bindings

    _load_agent_bindings.cache_clear()
    yield
    _load_agent_bindings.cache_clear()
