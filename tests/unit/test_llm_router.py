"""Tests for LLM routing logic."""

from unittest.mock import MagicMock

from juris.core.llm_router import LLMProvider, LLMRouter, LLMTask


def _make_settings(has_api_key: bool = True) -> MagicMock:
    settings = MagicMock()
    settings.anthropic_api_key = "sk-test" if has_api_key else None
    return settings


class TestLLMRouter:
    def test_pii_always_routes_local(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.RESEARCH, contains_pii=True)
        assert route.provider == LLMProvider.OLLAMA
        assert route.contains_pii is True

    def test_research_defaults_to_cloud(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.RESEARCH, contains_pii=False)
        assert route.provider == LLMProvider.ANTHROPIC

    def test_analyze_defaults_to_local(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.ANALYZE)
        assert route.provider == LLMProvider.OLLAMA

    def test_no_api_key_falls_back_to_ollama(self) -> None:
        router = LLMRouter(_make_settings(has_api_key=False))
        route = router.route(LLMTask.RESEARCH, contains_pii=False)
        assert route.provider == LLMProvider.OLLAMA

    def test_override(self) -> None:
        router = LLMRouter(_make_settings())
        router.override(LLMTask.DRAFT, LLMProvider.ANTHROPIC)
        route = router.route(LLMTask.DRAFT, contains_pii=False)
        assert route.provider == LLMProvider.ANTHROPIC

    def test_override_ignored_when_pii(self) -> None:
        router = LLMRouter(_make_settings())
        router.override(LLMTask.DRAFT, LLMProvider.ANTHROPIC)
        route = router.route(LLMTask.DRAFT, contains_pii=True)
        assert route.provider == LLMProvider.OLLAMA
