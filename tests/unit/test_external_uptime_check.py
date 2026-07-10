"""Contract tests for the public uptime probe used outside the Mac Mini."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_external_uptime.py"
WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "uptime.yml"


def _module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("check_external_uptime", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_compiles() -> None:
    subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPT)], check=True)  # noqa: S603


def test_external_probe_accepts_landing_200_and_health_401() -> None:
    mod = _module()

    def opener(url: str, timeout: float) -> int:
        assert timeout == 2
        return 401 if url.endswith("/api/health") else 200

    results = mod.run_checks("https://causia.com.br/", timeout=2, opener=opener)

    assert [r.ok for r in results] == [True, True]
    assert [r.status_code for r in results] == [200, 401]


def test_external_probe_fails_on_tunnel_or_dns_error() -> None:
    mod = _module()

    def opener(url: str, timeout: float) -> int:
        raise URLError("cloudflare tunnel unavailable")

    results = mod.run_checks("https://causia.com.br/", opener=opener)

    assert not any(r.ok for r in results)
    assert all("URLError" in r.error for r in results)


def test_workflow_runs_the_external_uptime_script_on_schedule() -> None:
    body = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "*/5 * * * *"' in body
    assert "scripts/check_external_uptime.py" in body
    assert "causia.com.br" in body
