# tests/unit/agent/test_update.py
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _keypair() -> tuple[str, Ed25519PrivateKey]:
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return pub_pem, priv


def _sign(priv: Ed25519PrivateKey, meta: dict) -> dict:
    from juris.agent.update import _signed_payload

    sig = priv.sign(_signed_payload(meta))
    return {**meta, "signature_alg": "ed25519", "signature": base64.b64encode(sig).decode()}


def test_valid_manifest_verifies() -> None:
    from juris.agent.update import verify_manifest

    pub, priv = _keypair()
    meta = _sign(priv, {"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y"})
    assert verify_manifest(meta, pub) is True


def test_tampered_manifest_rejected() -> None:
    from juris.agent.update import verify_manifest

    pub, priv = _keypair()
    meta = _sign(priv, {"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y"})
    meta["sha256"] = "b" * 64  # adulterado após assinar
    assert verify_manifest(meta, pub) is False


def test_wrong_key_rejected() -> None:
    from juris.agent.update import verify_manifest

    pub_other, _ = _keypair()
    _, priv = _keypair()
    meta = _sign(priv, {"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y"})
    assert verify_manifest(meta, pub_other) is False


def test_version_newer_comparison() -> None:
    from juris.agent.update import is_newer

    assert is_newer("2026.7.4.2", current="2026.7.4.1") is True
    assert is_newer("2026.7.4.1", current="2026.7.4.1") is False
    assert is_newer("2026.6.30.9", current="2026.7.1.0") is False
