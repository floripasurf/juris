# tests/unit/agent/test_update.py
from __future__ import annotations

import base64
import hashlib
import sys
import types
from typing import Any

import httpx
import pytest
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


class _FakeResp:
    """Resposta httpx mínima com `.json()` e `.content`."""

    def __init__(self, *, json_data: Any = None, content: bytes = b"") -> None:
        self._json = json_data
        self.content = content

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def test_sha256_mismatch_rejected_and_apply_never_called(monkeypatch: pytest.MonkeyPatch) -> None:
    # Manifesto validamente assinado, mas o blob baixado NÃO bate com o sha256 assinado:
    # deve rejeitar e nunca chamar _apply_update (segunda metade da fronteira de segurança).
    from juris.agent import update as update_mod

    monkeypatch.setenv("JURIS_AGENT_VERSION", "1.0.0")
    pub, priv = _keypair()
    served_blob = b"the-actual-served-bytes"
    wrong_sha = hashlib.sha256(b"a-completely-different-blob").hexdigest()
    # Basename compatível com o guard de binário cru — o teste deve alcançar o gate de sha256.
    url = f"https://dl/{update_mod._RAW_BINARY_BASENAME}"
    meta = _sign(priv, {"version": "2.0.0", "sha256": wrong_sha, "url": url})

    apply_calls = 0

    def fake_apply(blob: bytes) -> bool:
        nonlocal apply_calls
        apply_calls += 1
        return True

    monkeypatch.setattr(update_mod, "_apply_update", fake_apply)

    def fake_get(url: str, **_: Any) -> _FakeResp:
        if url == update_mod._MANIFEST_URL:
            return _FakeResp(json_data=meta)
        return _FakeResp(content=served_blob)

    monkeypatch.setattr(httpx, "get", fake_get)

    assert update_mod.maybe_self_update(public_key_pem=pub) is False
    assert apply_calls == 0  # troca de binário jamais alcançada


def test_stale_version_short_circuits_and_never_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    # Versão do manifesto == atual: is_newer curto-circuita ANTES de baixar o blob.
    from juris.agent import update as update_mod

    monkeypatch.setenv("JURIS_AGENT_VERSION", "2.0.0")
    pub, priv = _keypair()
    meta = _sign(priv, {"version": "2.0.0", "sha256": "a" * 64, "url": "https://dl/agent"})

    fetched: list[str] = []

    def fake_get(url: str, **_: Any) -> _FakeResp:
        fetched.append(url)
        if url == update_mod._MANIFEST_URL:
            return _FakeResp(json_data=meta)
        return _FakeResp(content=b"must-not-be-fetched")

    monkeypatch.setattr(httpx, "get", fake_get)
    # Se o código erroneamente prosseguisse, isto retornaria True e falharia o assert.
    monkeypatch.setattr(update_mod, "_apply_update", lambda _blob: True)

    assert update_mod.maybe_self_update(public_key_pem=pub) is False
    assert fetched == [update_mod._MANIFEST_URL]  # URL do blob nunca foi buscada


def test_no_public_key_returns_false_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sem chave pública embutida: retorno imediato False, sem tocar a rede.
    from juris.agent import update as update_mod

    def boom(*_: Any, **__: Any) -> _FakeResp:
        raise AssertionError("a rede não pode ser tocada sem chave pública")

    monkeypatch.setattr(httpx, "get", boom)

    assert update_mod.maybe_self_update(public_key_pem="") is False


def test_valid_newer_manifest_reaches_apply_update(monkeypatch: pytest.MonkeyPatch) -> None:
    # Controle positivo: manifesto genuinamente válido + versão mais nova + sha256 que
    # BATE com o blob servido → maybe_self_update chega a _apply_update exatamente uma vez
    # com os bytes corretos. Prova que os testes "never called" não passam vacuamente
    # (i.e., o caminho feliz REALMENTE alcança a troca; se assim não fosse, aqueles
    # testes provariam nada).
    from juris.agent import update as update_mod

    monkeypatch.setenv("JURIS_AGENT_VERSION", "1.0.0")
    pub, priv = _keypair()
    served_blob = b"the-legit-signed-payload-bytes"
    good_sha = hashlib.sha256(served_blob).hexdigest()
    # URL de binário cru da plataforma atual — a única forma que pode alcançar o swap.
    url = f"https://dl/{update_mod._RAW_BINARY_BASENAME}"
    meta = _sign(priv, {"version": "2.0.0", "sha256": good_sha, "url": url})

    applied: list[bytes] = []

    def spy_apply(blob: bytes) -> bool:
        applied.append(blob)
        return True

    monkeypatch.setattr(update_mod, "_apply_update", spy_apply)

    def fake_get(url: str, **_: Any) -> _FakeResp:
        if url == update_mod._MANIFEST_URL:
            return _FakeResp(json_data=meta)
        return _FakeResp(content=served_blob)

    monkeypatch.setattr(httpx, "get", fake_get)

    assert update_mod.maybe_self_update(public_key_pem=pub) is True
    assert applied == [served_blob]  # chamado exatamente uma vez, com os bytes certos


@pytest.mark.parametrize("installer_url", ["https://x/CausiaAgente.dmg", "https://x/causia-agent.zip"])
def test_installer_url_never_swaps_binary(monkeypatch: pytest.MonkeyPatch, installer_url: str) -> None:
    # Pino da correção de corrupção: manifesto v1 aponta p/ instalador (.dmg/.zip).
    # Mesmo com assinatura válida + versão mais nova + sha256 batendo, o guard de
    # binário cru retorna False ANTES de baixar — os.replace(sys.executable, <dmg>)
    # corromperia a instalação.
    from juris.agent import update as update_mod

    monkeypatch.setenv("JURIS_AGENT_VERSION", "1.0.0")
    pub, priv = _keypair()
    served_blob = b"installer-image-bytes"
    good_sha = hashlib.sha256(served_blob).hexdigest()
    meta = _sign(priv, {"version": "2.0.0", "sha256": good_sha, "url": installer_url})

    applied: list[bytes] = []
    monkeypatch.setattr(update_mod, "_apply_update", lambda blob: applied.append(blob) or True)

    fetched: list[str] = []

    def fake_get(url: str, **_: Any) -> _FakeResp:
        fetched.append(url)
        if url == update_mod._MANIFEST_URL:
            return _FakeResp(json_data=meta)
        return _FakeResp(content=served_blob)

    monkeypatch.setattr(httpx, "get", fake_get)

    assert update_mod.maybe_self_update(public_key_pem=pub) is False
    assert applied == []  # nunca troca o executável
    assert fetched == [update_mod._MANIFEST_URL]  # instalador nem sequer é baixado


def test_release_meta_resolution_env_wins_else_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Injeta um _release_meta falso (como o CI geraria no build) e verifica a
    # ordem de resolução: env vence → senão embutido → senão juris.__version__.
    from juris import __version__
    from juris.agent import update as update_mod

    embedded_pem = "-----BEGIN PUBLIC KEY-----\nembutida\n-----END PUBLIC KEY-----\n"
    fake = types.ModuleType("juris.agent._release_meta")
    fake.AGENT_VERSION = "2026.7.4.1"  # type: ignore[attr-defined]
    fake.PUBLIC_KEY_PEM = embedded_pem  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "juris.agent._release_meta", fake)

    # Sem env → embutido vence
    monkeypatch.delenv("JURIS_AGENT_VERSION", raising=False)
    monkeypatch.delenv("JURIS_AGENT_UPDATE_PUBKEY", raising=False)
    assert update_mod.current_version() == "2026.7.4.1"
    assert update_mod._resolve_public_key() == embedded_pem

    # Env presente → env vence (override dev/teste)
    monkeypatch.setenv("JURIS_AGENT_VERSION", "9.9.9.9")
    monkeypatch.setenv("JURIS_AGENT_UPDATE_PUBKEY", "pem-do-env")
    assert update_mod.current_version() == "9.9.9.9"
    assert update_mod._resolve_public_key() == "pem-do-env"

    # Sem env e sem módulo embutido → cai em juris.__version__ / chave vazia
    monkeypatch.delenv("JURIS_AGENT_VERSION", raising=False)
    monkeypatch.delenv("JURIS_AGENT_UPDATE_PUBKEY", raising=False)
    monkeypatch.delitem(sys.modules, "juris.agent._release_meta", raising=False)
    assert update_mod.current_version() == __version__
    assert update_mod._resolve_public_key() == ""
