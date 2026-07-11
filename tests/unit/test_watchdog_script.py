"""Contrato + lógica de two-strike do causia_watchdog.sh.

O watchdog só faz kickstart após 2 falhas seguidas de HTTP; qualquer status HTTP
(inclusive 401) conta como vivo. O teste injeta `curl`/`launchctl` falsos via PATH
para exercitar o contador sem tocar em launchd real.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "causia_watchdog.sh"


def test_script_exists_and_is_valid_sh() -> None:
    assert SCRIPT.exists()
    subprocess.run(["/bin/sh", "-n", str(SCRIPT)], check=True)  # noqa: S603


def test_script_uses_two_strike_kickstart() -> None:
    body = SCRIPT.read_text()
    assert "launchctl kickstart" in body
    assert "-ge 2" in body
    assert "/api/health" in body


def _fake_bin(tmp_path: Path, curl_code: str, kick_log: Path) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f"#!/bin/sh\nprintf '%s' '{curl_code}'\n")
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(f'#!/bin/sh\necho "$@" >> "{kick_log}"\n')
    for f in (curl, launchctl):
        f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run(script_env: dict[str, str], bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **script_env}
    return subprocess.run(  # noqa: S603
        ["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True, check=True
    )


def test_single_failure_does_not_kickstart(tmp_path: Path) -> None:
    kick_log = tmp_path / "kicks.log"
    bin_dir = _fake_bin(tmp_path, "000", kick_log)
    state = tmp_path / "state"
    _run({"CAUSIA_WATCHDOG_STATE": str(state)}, bin_dir)
    assert not kick_log.exists()  # 1 falha só → sem kickstart
    assert state.read_text().strip() == "1"


def test_two_consecutive_failures_kickstart_once(tmp_path: Path) -> None:
    kick_log = tmp_path / "kicks.log"
    bin_dir = _fake_bin(tmp_path, "000", kick_log)
    state = tmp_path / "state"
    _run({"CAUSIA_WATCHDOG_STATE": str(state)}, bin_dir)
    result = _run({"CAUSIA_WATCHDOG_STATE": str(state), "CAUSIA_WEB_LABEL": "com.causia.web"}, bin_dir)
    assert kick_log.exists()
    kicks = kick_log.read_text().strip().splitlines()
    assert len(kicks) == 1
    assert "com.causia.web" in kicks[0]
    assert "kickstart" in kicks[0]
    assert "kickstart" in result.stdout
    # Contador zera após o kickstart para não disparar em loop.
    assert state.read_text().strip() == "0"


def test_http_response_resets_counter(tmp_path: Path) -> None:
    kick_log = tmp_path / "kicks.log"
    state = tmp_path / "state"
    # 1ª falha
    _run({"CAUSIA_WATCHDOG_STATE": str(state)}, _fake_bin(tmp_path, "000", kick_log))
    # 2ª execução com HTTP 401 (vivo) → reseta, não conta como 2ª falha
    up_bin = tmp_path / "upbin"
    up_bin.mkdir()
    (up_bin / "curl").write_text("#!/bin/sh\nprintf '%s' '401'\n")
    (up_bin / "curl").chmod(0o755)
    (up_bin / "launchctl").write_text(f'#!/bin/sh\necho "$@" >> "{kick_log}"\n')
    (up_bin / "launchctl").chmod(0o755)
    _run({"CAUSIA_WATCHDOG_STATE": str(state)}, up_bin)
    assert not kick_log.exists()  # nunca deu kickstart
    assert not state.exists()  # estado limpo após resposta viva
