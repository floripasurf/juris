"""The AI-of-preference (ADR-0018) is actually wired into _build_llm, not dead code."""

from __future__ import annotations


def test_ai_preference_off_by_default_keeps_local_llm(monkeypatch) -> None:
    from juris.web import demo_service

    monkeypatch.delenv("JURIS_AI_PREFERENCE", raising=False)
    llm = demo_service._build_llm(use_cloud=False)
    # Default posture unchanged: a plain local backend, not the browser-preference chain.
    assert "→" not in llm.model_name


def test_ai_preference_wraps_browser_session_with_fallback(monkeypatch) -> None:
    """JURIS_AI_PREFERENCE=1 routes _build_llm through build_ai_of_preference."""
    from juris.api import browser_bridge
    from juris.web import demo_service

    monkeypatch.setenv("JURIS_AI_PREFERENCE", "1")
    monkeypatch.setenv("JURIS_BROWSER_BRIDGE_URL", "ws://127.0.0.1:8777")

    class _StubChannel:
        async def request(self, message: dict[str, object]) -> dict[str, object]:
            return {}

    # Avoid opening a real WebSocket to the (absent) native bridge.
    monkeypatch.setattr(
        browser_bridge.WebSocketBridgeChannel,
        "to_localhost",
        classmethod(lambda cls, url, **kw: _StubChannel()),
    )

    llm = demo_service._build_llm(use_cloud=False)
    # FallbackLLM.model_name is "<primary>→<fallback>" — proof the browser session
    # is primary with a backend fallback, i.e. build_ai_of_preference ran.
    assert "→" in llm.model_name
    assert "browser session" in llm.model_name


def test_ai_preference_local_fallback_still_ner_deids_the_browser(monkeypatch) -> None:
    """P0 regression: the browser session is a CLOUD service (claude.ai), so it must be
    de-identified with NER and fail-closed EVEN when the fallback is the local Ollama."""
    from juris.api import browser_bridge
    from juris.core import deid_llm
    from juris.web import demo_service

    monkeypatch.setenv("JURIS_AI_PREFERENCE", "1")
    monkeypatch.setenv("JURIS_BROWSER_BRIDGE_URL", "ws://127.0.0.1:8777")
    # Stub the NER so no heavy model loads; it just has to be a non-None redactor.
    monkeypatch.setattr(deid_llm, "default_ner_redactor", lambda: (lambda _t: []))

    class _StubChannel:
        async def request(self, message: dict) -> dict:
            return {}

    monkeypatch.setattr(
        browser_bridge.WebSocketBridgeChannel,
        "to_localhost",
        classmethod(lambda cls, url, **kw: _StubChannel()),
    )

    llm = demo_service._build_llm(use_cloud=False)  # local fallback path
    browser_wrap = llm._primary  # FallbackLLM primary = the de-id-wrapped browser
    assert browser_wrap._allow_partial is False  # fail-closed
    assert browser_wrap._ner is not None  # NER active → names removed before claude.ai
