"""Tests for LLM routing logic."""

from unittest.mock import MagicMock

import pytest

from juris.core.llm_router import LLMProvider, LLMRouter, LLMTask, PIIMode


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


class TestPIIModesAndDeid:
    def test_local_raw_is_default_and_stays_local(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.DRAFT, contains_pii=True)  # default LOCAL_RAW
        assert route.provider == LLMProvider.OLLAMA
        assert route.deidentify is False

    def test_cloud_deid_routes_cloud_with_deidentify_flag(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.CLOUD_DEID)
        assert route.provider == LLMProvider.ANTHROPIC
        assert route.deidentify is True

    def test_cloud_raw_routes_cloud_without_deidentify(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.CLOUD_RAW)
        assert route.provider == LLMProvider.ANTHROPIC
        assert route.deidentify is False

    def test_cloud_deid_without_key_falls_back_local(self) -> None:
        router = LLMRouter(_make_settings(has_api_key=False))
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.CLOUD_DEID)
        assert route.provider == LLMProvider.OLLAMA
        assert route.deidentify is False  # local — no de-id needed

    def test_prepare_payload_deidentifies_when_route_demands_it(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.CLOUD_DEID)
        text, mapping = router.prepare_payload(route, "Autor CPF 123.456.789-09", allow_partial=True)
        assert "123.456.789-09" not in text
        assert mapping  # re-id map for the caller

    def test_prepare_payload_blocks_partial_deid_without_optin(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.CLOUD_DEID)
        with pytest.raises(ValueError, match="parcial"):
            router.prepare_payload(route, "Autor CPF 123.456.789-09")  # no NER, no opt-in → fail closed

    def test_prepare_payload_passthrough_when_not_deidentify(self) -> None:
        router = LLMRouter(_make_settings())
        route = router.route(LLMTask.DRAFT, contains_pii=True)  # LOCAL_RAW
        text, mapping = router.prepare_payload(route, "Autor CPF 123.456.789-09")
        assert text == "Autor CPF 123.456.789-09"
        assert mapping == {}

    def test_browser_deid_routes_to_browser_session_with_deid(self) -> None:
        # Lawyer's own Claude/ChatGPT subscription via the browser extension.
        # De-id stays ON (consumer plans may train) — defense in depth.
        router = LLMRouter(_make_settings(has_api_key=False))  # no API key needed
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.BROWSER_DEID)
        assert route.provider == LLMProvider.BROWSER
        assert route.provider.value == "browser"
        assert route.deidentify is True
        assert route.model == "browser session"
