"""AI-session status for the operator console (ADR-0016/0018).

Tells the operator which AI is active and whether prompts are de-identified before
leaving the machine — the answer the lawyer needs before clicking "draft".
"""

from __future__ import annotations

import os


def ai_session_status(
    *, anthropic_key: bool, browser_bridge: bool, ollama_reachable: bool
) -> dict[str, object]:
    """Resolve the active AI mode + de-id posture from what's available.

    Precedence: the lawyer's browser session (ADR-0018) > cloud API (de-identified)
    > local model. De-id is on for any off-device AI; local keeps PII on the box.
    """
    if browser_bridge:
        mode = "browser_session"
    elif anthropic_key:
        mode = "cloud_deid"
    else:
        mode = "local"
    return {
        "mode": mode,
        "deidentify": mode != "local",
        "providers": {"cloud": anthropic_key, "browser": browser_bridge, "local": ollama_reachable},
    }


def resolve_ai_session_status() -> dict[str, object]:
    """Build the status from the live environment (the endpoint's entry point)."""
    return ai_session_status(
        anthropic_key=bool(os.environ.get("ANTHROPIC_API_KEY")),
        browser_bridge=bool(os.environ.get("JURIS_BROWSER_BRIDGE_URL")),
        ollama_reachable=bool(os.environ.get("OLLAMA_URL")),
    )
