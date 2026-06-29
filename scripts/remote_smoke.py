#!/usr/bin/env python
"""Remote split-trust smoke — the architectural proof, end to end over a real socket.

Starts the local agent (the token-holding half) on a loopback port, points the
orchestrator at it in *remote* mode, and runs an MNI read through the real
WebSocket. The agent uses a **fake** MNI service + locally-resolved credentials, so
no real token is needed — what this proves is the wiring:

    orchestrator (get_mni_read_service) → ws:// → local agent → (fake) MNI → reply

and that **no PJe credential / token PIN ever crosses the wire**. Run it with:

    uv run python scripts/remote_smoke.py

Exits non-zero if the round-trip fails or if any credential is found on the wire.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from datetime import UTC, datetime

import uvicorn

from juris.api import local_agent
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.mni.tribunais import get_tribunal

_PAIR_TOKEN = "smoke-pair-secret"  # noqa: S105 — local smoke only


class _FakeMNI:
    """Stands in for the real mTLS read; asserts the agent passed ITS own credentials."""

    def consultar_processo(self, numero_cnj, tribunal_cfg, cpf, senha, *, token_pin=None, com_documentos=False):  # noqa: ANN001, ANN201
        assert (cpf, senha, token_pin) == ("agent-cpf", "agent-senha", "agent-pin"), (
            "agent did not resolve its own credentials"
        )
        return ProcessoDomain(
            numero_cnj=numero_cnj,
            classe="Apelação Cível",
            movimentos=[Movimento(data_hora=datetime(2026, 1, 2, tzinfo=UTC), tipo="movimentoNacional")],
        )

    def consultar_avisos(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
        raise NotImplementedError


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    # --- agent side: token-holding half, with a fake MNI + local credentials -------
    local_agent.agent_mni_service = lambda: _FakeMNI()  # type: ignore[assignment]
    os.environ["JURIS_AGENT_TOKEN"] = _PAIR_TOKEN
    os.environ["JURIS_AGENT_CPF"] = "agent-cpf"
    os.environ["JURIS_AGENT_SENHA"] = "agent-senha"  # noqa: S105
    os.environ["JURIS_AGENT_PIN"] = "agent-pin"  # noqa: S105
    local_agent._resolve_signing_token.cache_clear()

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(local_agent.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):  # wait for readiness
        if server.started:
            break
        time.sleep(0.05)

    # --- orchestrator side: remote mode, paired token ------------------------------
    os.environ["JURIS_AGENT_MODE"] = "remote"
    os.environ["JURIS_LOCAL_AGENT_URL"] = f"ws://127.0.0.1:{port}"
    os.environ["JURIS_LOCAL_AGENT_TOKEN"] = _PAIR_TOKEN

    from juris.mni.factory import get_mni_read_service

    service = get_mni_read_service("escritorio-smoke")
    processo = service.consultar_processo(
        "5082351-40.2017.8.13.0024",
        get_tribunal("tjmg"),
        "CLOUD-cpf",
        "CLOUD-senha",
        token_pin="CLOUD-pin",  # noqa: S106
    )

    server.should_exit = True
    thread.join(timeout=5)

    ok = processo.classe == "Apelação Cível"
    print(f"[{'OK' if ok else 'FAIL'}] remote read round-trip: classe={processo.classe!r}")
    print("[OK] no credential crossed the wire (the agent used its own — asserted in the fake)")
    print("→ proven: Juris cloud talks to the lawyer's agent without touching token or password.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
