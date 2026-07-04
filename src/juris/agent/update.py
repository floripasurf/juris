# src/juris/agent/update.py
"""Auto-update do agente com manifesto assinado Ed25519 (padrão do conector lida).

Um servidor comprometido não injeta binário malicioso: o manifesto é assinado com
uma chave privada que vive fora do servidor (só no CI), e o agente valida com a
chave pública embutida antes de trocar o binário."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_MANIFEST_URL = os.environ.get("JURIS_AGENT_UPDATE_URL", "https://causia.com.br/api/agent/latest")
# Substituída na release pela chave pública real (a privada fica só no CI).
_UPDATE_PUBLIC_KEY_PEM = os.environ.get("JURIS_AGENT_UPDATE_PUBKEY", "")
_SIGNED_FIELDS = ("version", "sha256", "url")


def _signed_payload(meta: dict[str, Any]) -> bytes:
    payload = {k: meta[k] for k in _SIGNED_FIELDS if k in meta}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_pub(pem: str) -> Ed25519PublicKey:
    key = load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("chave pública não é Ed25519")
    return key


def verify_manifest(meta: dict[str, Any], public_key_pem: str) -> bool:
    """Valida a assinatura Ed25519 de um manifesto de atualização.

    Args:
        meta: Manifesto retornado pelo servidor, com ao menos `version`, `sha256`,
            `url`, `signature_alg` e `signature` (base64).
        public_key_pem: Chave pública Ed25519 em PEM usada para verificar a
            assinatura.

    Returns:
        True se a assinatura for válida para o payload canônico
        `{version, sha256, url}`; False em qualquer outro caso (algoritmo
        errado, assinatura ausente/corrompida, chave errada, payload
        adulterado).
    """
    if str(meta.get("signature_alg") or "").lower() != "ed25519":
        return False
    sig = str(meta.get("signature") or "")
    if not sig or not public_key_pem.strip():
        return False
    try:
        _load_pub(public_key_pem).verify(base64.b64decode(sig), _signed_payload(meta))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def is_newer(candidate: str, *, current: str) -> bool:
    """Compara duas versões no formato `YYYY.M.D.N` (ou similar, só dígitos).

    Args:
        candidate: Versão candidata (ex.: do manifesto remoto).
        current: Versão atualmente instalada.

    Returns:
        True se `candidate` for estritamente maior que `current` na comparação
        lexicográfica de tuplas de inteiros.
    """

    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    return parts(candidate) > parts(current)


def current_version() -> str:
    """Retorna a versão atual do agente (override via env para testes/CI).

    Returns:
        A versão em `JURIS_AGENT_VERSION`, ou `juris.__version__` como padrão.
    """
    from juris import __version__

    return os.environ.get("JURIS_AGENT_VERSION", __version__)


def maybe_self_update(*, public_key_pem: str | None = None) -> bool:
    """Verifica, baixa e aplica uma atualização assinada, se houver.

    Best-effort: baixa+troca se houver versão maior assinada. Nunca lança —
    qualquer falha de rede, verificação ou I/O resulta em `False`.

    Args:
        public_key_pem: Chave pública Ed25519 em PEM a usar na verificação.
            Se None, usa `_UPDATE_PUBLIC_KEY_PEM` (embutida/via env).

    Returns:
        True se uma atualização válida foi baixada e aplicada.
    """
    import httpx

    pub = public_key_pem if public_key_pem is not None else _UPDATE_PUBLIC_KEY_PEM
    if not pub:
        return False  # sem chave embutida → auto-update desligado (dev)
    try:
        meta = httpx.get(_MANIFEST_URL, timeout=10.0).json()
    except (httpx.HTTPError, ValueError):
        return False
    if not verify_manifest(meta, pub) or not is_newer(str(meta.get("version") or ""), current=current_version()):
        return False
    try:
        blob = httpx.get(str(meta["url"]), timeout=120.0, follow_redirects=True).content
    except httpx.HTTPError:
        return False
    if hashlib.sha256(blob).hexdigest() != str(meta.get("sha256") or ""):
        return False  # payload não confere com o manifesto assinado
    return _apply_update(blob)


def _apply_update(blob: bytes) -> bool:
    """Troca atômica do executável empacotado. No-op fora do PyInstaller.

    Args:
        blob: Conteúdo binário já verificado (assinatura + sha256) a gravar
            no lugar do executável atual.

    Returns:
        True se a troca foi aplicada; False se o processo não está rodando
        como binário PyInstaller (`sys.frozen`), caso em que não há o que
        trocar.
    """
    if not getattr(sys, "frozen", False):
        return False
    target = sys.executable
    tmp = f"{target}.new"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.chmod(tmp, 0o755)  # noqa: S103 - executável precisa do bit +x para rodar
    os.replace(tmp, target)  # atômico; efetiva no próximo start (launchd/Run key reinicia)
    return True
