#!/usr/bin/env python3
"""scripts/write_release_meta.py — gera src/juris/agent/_release_meta.py (gitignored).

Uso: uv run python scripts/write_release_meta.py <version>

Lê a chave pública Ed25519 (PEM, multi-linha) do env `AGENT_UPDATE_PUBKEY` e
escreve o módulo embutido consumido por `juris.agent.update` em tempo de
build. A serialização usa `json.dumps()` para escapar a PEM — nunca
interpolação ingênua de f-string/format — porque uma PEM contém quebras de
linha reais que quebrariam a sintaxe de uma string Python de linha única se
coladas cruas entre aspas.

Roda em AMBOS os jobs de build (macOS e Windows) como o MESMO script, para
que a lógica de escaping não divirja entre plataformas. É chamado ANTES do
PyInstaller: se este script falhar (version/chave ausente), o build falha
alto em vez de empacotar silenciosamente sem auto-update.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parent.parent / "src" / "juris" / "agent" / "_release_meta.py"

_HEADER = (
    '"""Gerado pelo CI de release (scripts/write_release_meta.py) — NÃO commitar.\n\n'
    "Contrato consumido por juris.agent.update._embedded_release_meta().\n"
    '"""\n'
)


def main() -> None:
    if len(sys.argv) != 2:
        print("uso: write_release_meta.py <version>", file=sys.stderr)
        raise SystemExit(2)
    version = sys.argv[1]
    pubkey = os.environ.get("AGENT_UPDATE_PUBKEY", "")
    if not version.strip() or not pubkey.strip():
        print(
            "erro: version (arg) e AGENT_UPDATE_PUBKEY (env) são obrigatórios",
            file=sys.stderr,
        )
        raise SystemExit(1)
    _TARGET.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"{_HEADER}"
        f"AGENT_VERSION = {json.dumps(version)}\n"
        f"PUBLIC_KEY_PEM = {json.dumps(pubkey)}\n"
    )
    _TARGET.write_text(content, encoding="utf-8")
    print(f"→ {_TARGET}")


if __name__ == "__main__":
    main()
