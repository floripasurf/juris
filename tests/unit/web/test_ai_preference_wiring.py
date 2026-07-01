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
