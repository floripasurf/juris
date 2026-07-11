"""Tests for the repo-local secret scanner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_scanner():
    script = Path(__file__).resolve().parents[2] / "scripts" / "scan_secrets.py"
    spec = importlib.util.spec_from_file_location("scan_secrets", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_secret_scan_flags_realistic_tokens(tmp_path: Path) -> None:
    scanner = _load_scanner()
    leaked = tmp_path / "leak.txt"
    leaked.write_text("OPENAI_API_KEY=" + "sk-proj-" + ("A" * 40), encoding="utf-8")

    findings = scanner.scan_paths([leaked])

    assert len(findings) == 1
    assert findings[0].kind == "openai_api_key"


def test_secret_scan_ignores_documented_placeholders(tmp_path: Path) -> None:
    scanner = _load_scanner()
    env = tmp_path / ".env.example"
    env.write_text(
        "\n".join(
            [
                "ANTHROPIC_API_KEY=sk-ant-...",
                "TOKEN_PIN=",
                "CERT_PASSWORD=",
            ]
        ),
        encoding="utf-8",
    )

    assert scanner.scan_paths([env]) == []


def test_secret_scan_respects_allowlist_marker(tmp_path: Path) -> None:
    scanner = _load_scanner()
    fixture = tmp_path / "fixture.txt"
    fixture.write_text(
        "OPENAI_API_KEY=" + "sk-proj-" + ("B" * 40) + "  # pragma: allowlist secret",
        encoding="utf-8",
    )

    assert scanner.scan_paths([fixture]) == []
