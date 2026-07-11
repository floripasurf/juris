"""C6 (spec 2026-07-05): campos de IA do run computados de draft + settings + helper."""

from __future__ import annotations

import pytest


def test_provider_fields_computed_from_draft_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """ai_model do draft, declarado do settings, warning do helper (canônicos)."""
    import juris.config as config
    from juris.llm.browser_session import label_to_browser_provider, provider_divergence

    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "chatgpt")
    monkeypatch.setattr(config, "_settings", None)

    declared = config.get_settings().ai_browser_provider
    ai_model = "claude.ai (browser session)"  # o que o draft de fato usou
    warning = provider_divergence(declared, label_to_browser_provider(ai_model))
    assert declared == "chatgpt"
    assert warning is not None and "Claude.ai" in warning

    # fallback local: label não-browser → sem warning (o próprio ai_model evidencia)
    assert provider_divergence(declared, label_to_browser_provider("qwen3:latest")) is None
