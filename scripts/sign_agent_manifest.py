#!/usr/bin/env python3
"""scripts/sign_agent_manifest.py — gera agent-latest.json assinado (Ed25519).

Uso: uv run python scripts/sign_agent_manifest.py <version> <installer_url> <artifact_path> > agent-latest.json

Importa `_signed_payload` de `juris.agent.update` (em vez de reimplementar a
canonicalização aqui) para que o payload assinado nunca possa divergir do que
o cliente (`verify_manifest`) recalcula na verificação.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from juris.agent.update import _signed_payload


def main() -> None:
    version, url, artifact = sys.argv[1], sys.argv[2], sys.argv[3]
    priv = load_pem_private_key(os.environ["AGENT_UPDATE_PRIVKEY"].encode(), password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    # sha256 em hex minúsculo — contrato com o cliente: juris.agent.update
    # compara meta["sha256"] (string) contra hashlib.sha256(blob).hexdigest()
    # do binário baixado via `==` de string. hexdigest() já retorna minúsculo
    # por padrão — não normalizar/alterar o case aqui, ou a comparação exata
    # do cliente deixa de bater.
    sha = hashlib.sha256(Path(artifact).read_bytes()).hexdigest()
    meta = {"version": version, "sha256": sha, "url": url}
    sig = priv.sign(_signed_payload(meta))
    print(
        json.dumps(
            {**meta, "signature_alg": "ed25519", "signature": base64.b64encode(sig).decode()},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
