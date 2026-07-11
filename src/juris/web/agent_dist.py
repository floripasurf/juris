"""Distribuição do agente: serve o manifesto de update assinado (público)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def agent_dist_dir() -> Path:
    """Directory the CI publishes ``agent-latest.json`` (and installers) into.

    Returns:
        The configured dist directory, or ``~/juris-pilot/agent-dist`` by default.
    """
    return Path(os.environ.get("JURIS_AGENT_DIST_DIR", str(Path.home() / "juris-pilot" / "agent-dist")))


def latest_manifest() -> dict[str, object] | None:
    """Read the signed auto-update manifest from the dist directory.

    Returns:
        The parsed ``agent-latest.json`` contents, or ``None`` if no manifest
        has been published yet.
    """
    path = agent_dist_dir() / "agent-latest.json"
    if not path.is_file():
        return None
    manifest: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return manifest
